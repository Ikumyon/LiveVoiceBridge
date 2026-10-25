use crate::audio::AudioClip;
use pyo3::exceptions::PyRuntimeError;
use pyo3::prelude::*;
use rodio::{Decoder, DeviceSinkBuilder, MixerDeviceSink, Player, Source};
use std::collections::VecDeque;
use std::path::{Path, PathBuf};
use std::sync::{mpsc, Arc, Mutex};
use std::thread::JoinHandle;
use std::time::Duration;

struct ClipSource {
    clip: AudioClip,
    position: usize,
}
impl Iterator for ClipSource {
    type Item = f32;
    fn next(&mut self) -> Option<f32> {
        let sample = *self.clip.samples.get(self.position)?;
        self.position += 1;
        Some(sample as f32 / 32768.0)
    }
}
impl Source for ClipSource {
    fn current_span_len(&self) -> Option<usize> {
        Some(self.clip.samples.len() - self.position)
    }
    fn channels(&self) -> rodio::ChannelCount {
        self.clip
            .format
            .channels
            .try_into()
            .expect("validated channels")
    }
    fn sample_rate(&self) -> rodio::SampleRate {
        self.clip
            .format
            .sample_rate
            .try_into()
            .expect("validated sample rate")
    }
    fn total_duration(&self) -> Option<Duration> {
        Some(Duration::from_secs_f64(
            self.clip.samples.len() as f64
                / self.clip.format.channels as f64
                / self.clip.format.sample_rate as f64,
        ))
    }
}

type Reply = mpsc::Sender<Result<(), String>>;
enum Request {
    Speech(AudioClip, Reply),
    Effect(PathBuf, bool, Reply),
    Close,
}
struct Active {
    player: Player,
    done: Option<Reply>,
    effect: bool,
}

fn worker(receiver: mpsc::Receiver<Request>, errors: Arc<Mutex<VecDeque<String>>>) {
    let fault = Arc::new(Mutex::new(None));
    let mut device: Option<MixerDeviceSink> = None;
    let mut active: Vec<Active> = Vec::new();
    loop {
        let message = if active.is_empty() && device.is_some() {
            receiver.recv_timeout(Duration::from_secs(2))
        } else if active.is_empty() {
            receiver
                .recv()
                .map_err(|_| mpsc::RecvTimeoutError::Disconnected)
        } else {
            receiver.recv_timeout(Duration::from_millis(10))
        };
        let timed_out = matches!(&message, Err(mpsc::RecvTimeoutError::Timeout));
        if let Ok(request) = message {
            if matches!(request, Request::Close) {
                break;
            }
            let (clip, path, overlap, reply) = match request {
                Request::Speech(clip, reply) => (Some(clip), None, false, reply),
                Request::Effect(path, overlap, reply) => (None, Some(path), overlap, reply),
                Request::Close => unreachable!(),
            };
            let effect = path.is_some();
            if effect && active.iter().filter(|item| item.effect).count() >= 16 {
                let _ = reply.send(Err("同時に再生する効果音の上限に達しました。".into()));
                continue;
            }
            if device.is_none() {
                let fault = Arc::clone(&fault);
                let opened = DeviceSinkBuilder::from_default_device().and_then(|builder| {
                    builder
                        .with_error_callback(move |error| {
                            if let Ok(mut slot) = fault.lock() {
                                *slot = Some(format!("音声装置エラー: {error}"));
                            }
                        })
                        .open_stream()
                });
                match opened {
                    Ok(mut output) => {
                        output.log_on_drop(false);
                        device = Some(output);
                    }
                    Err(error) => {
                        let _ = reply.send(Err(error.to_string()));
                        continue;
                    }
                }
            }
            let player = Player::connect_new(device.as_ref().expect("opened device").mixer());
            if let Some(clip) = clip {
                player.append(ClipSource { clip, position: 0 });
            } else if let Some(path) = path {
                let decoded = std::fs::File::open(path)
                    .map_err(|e| e.to_string())
                    .and_then(|file| Decoder::try_from(file).map_err(|e| e.to_string()));
                match decoded {
                    Ok(source) => player.append(source),
                    Err(error) => {
                        let _ = reply.send(Err(error));
                        continue;
                    }
                }
            }
            let done = if overlap {
                let _ = reply.send(Ok(()));
                None
            } else {
                Some(reply)
            };
            active.push(Active {
                player,
                done,
                effect,
            });
        } else if matches!(message, Err(mpsc::RecvTimeoutError::Disconnected)) {
            break;
        }
        if active.is_empty() && timed_out {
            device = None;
        }
        let error = fault.lock().ok().and_then(|mut value| value.take());
        if let Some(error) = error {
            for item in active.drain(..) {
                item.player.stop();
                if let Some(done) = item.done {
                    let _ = done.send(Err(error.clone()));
                }
            }
            if let Ok(mut queue) = errors.lock() {
                if queue.len() == 16 {
                    queue.pop_front();
                }
                queue.push_back(error);
            }
            device = None;
            continue;
        }
        let mut index = 0;
        while index < active.len() {
            if active[index].player.empty() {
                let item = active.swap_remove(index);
                if let Some(done) = item.done {
                    let _ = done.send(Ok(()));
                }
            } else {
                index += 1;
            }
        }
    }
    for item in active {
        item.player.stop();
        if let Some(done) = item.done {
            let _ = done.send(Err("音声出力を終了しました。".into()));
        }
    }
}

#[pyclass]
pub struct AudioPlayer {
    sender: Mutex<Option<mpsc::SyncSender<Request>>>,
    thread: Mutex<Option<JoinHandle<()>>>,
    sounds: PathBuf,
    errors: Arc<Mutex<VecDeque<String>>>,
}

impl AudioPlayer {
    fn request(&self, make: impl FnOnce(Reply) -> Request) -> Result<(), String> {
        let (reply, result) = mpsc::channel();
        let sender = self
            .sender
            .lock()
            .map_err(|e| e.to_string())?
            .clone()
            .ok_or("音声出力は終了しています。")?;
        sender.send(make(reply)).map_err(|e| e.to_string())?;
        result.recv().map_err(|e| e.to_string())?
    }
    fn shutdown(&self) -> Result<(), String> {
        if let Some(sender) = self.sender.lock().map_err(|e| e.to_string())?.take() {
            let _ = sender.send(Request::Close);
        }
        if let Some(thread) = self.thread.lock().map_err(|e| e.to_string())?.take() {
            thread
                .join()
                .map_err(|_| "音声処理スレッドが異常終了しました。")?;
        }
        Ok(())
    }
}

#[pymethods]
impl AudioPlayer {
    #[new]
    fn new(sounds: String) -> PyResult<Self> {
        let sounds = Path::new(&sounds)
            .canonicalize()
            .map_err(|e| PyRuntimeError::new_err(e.to_string()))?;
        let (sender, receiver) = mpsc::sync_channel(16);
        let errors = Arc::new(Mutex::new(VecDeque::new()));
        let worker_errors = Arc::clone(&errors);
        let thread = std::thread::Builder::new()
            .name("native-audio".into())
            .spawn(move || worker(receiver, worker_errors))
            .map_err(|e| PyRuntimeError::new_err(e.to_string()))?;
        Ok(Self {
            sender: Mutex::new(Some(sender)),
            thread: Mutex::new(Some(thread)),
            sounds,
            errors,
        })
    }
    fn play(&self, py: Python<'_>, clip: &AudioClip) -> PyResult<()> {
        let clip = clip.clone();
        py.detach(|| self.request(|reply| Request::Speech(clip, reply)))
            .map_err(PyRuntimeError::new_err)
    }
    fn sound(&self, py: Python<'_>, filename: String, overlap: bool) -> PyResult<()> {
        py.detach(|| {
            let name = Path::new(filename.rsplit(['/', '\\']).next().unwrap_or(""));
            if name.components().count() != 1 || name.file_name().is_none() {
                return Err("効果音はファイル名で指定してください。".into());
            }
            let path = self
                .sounds
                .join(name)
                .canonicalize()
                .map_err(|e| e.to_string())?;
            if path.parent() != Some(self.sounds.as_path()) {
                return Err("効果音が保存先の外を指しています。".into());
            }
            self.request(|reply| Request::Effect(path, overlap, reply))
        })
        .map_err(PyRuntimeError::new_err)
    }
    fn drain_errors(&self) -> Vec<String> {
        self.errors
            .lock()
            .map(|mut queue| queue.drain(..).collect())
            .unwrap_or_default()
    }
    fn close(&self, py: Python<'_>) -> PyResult<()> {
        py.detach(|| self.shutdown())
            .map_err(PyRuntimeError::new_err)
    }
}
impl Drop for AudioPlayer {
    fn drop(&mut self) {
        let _ = self.shutdown();
    }
}
