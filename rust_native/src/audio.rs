use std::fs::{self, OpenOptions};
use std::io::Write;
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicU64, Ordering};
use std::time::{SystemTime, UNIX_EPOCH};

use pyo3::buffer::PyBuffer;
use pyo3::exceptions::{PyIOError, PyValueError};
use pyo3::prelude::*;
use pyo3::types::{PyAny, PyBytes};

static TEMP_SEQUENCE: AtomicU64 = AtomicU64::new(0);

#[derive(Clone, Copy)]
struct WavFormat {
    channels: u16,
    sample_rate: u32,
}

fn read_u16(data: &[u8], offset: usize) -> Result<u16, String> {
    let bytes = data
        .get(offset..offset + 2)
        .ok_or_else(|| "WAVヘッダーが途中で終了しています".to_string())?;
    Ok(u16::from_le_bytes([bytes[0], bytes[1]]))
}

fn read_u32(data: &[u8], offset: usize) -> Result<u32, String> {
    let bytes = data
        .get(offset..offset + 4)
        .ok_or_else(|| "WAVヘッダーが途中で終了しています".to_string())?;
    Ok(u32::from_le_bytes([bytes[0], bytes[1], bytes[2], bytes[3]]))
}

fn decode_pcm16_wav(data: &[u8]) -> Result<(WavFormat, Vec<i16>), String> {
    if data.len() < 12 || &data[0..4] != b"RIFF" || &data[8..12] != b"WAVE" {
        return Err("RIFF/WAVE形式ではありません".to_string());
    }

    let mut format = None;
    let mut pcm: Option<Vec<i16>> = None;
    let mut offset = 12usize;
    while offset + 8 <= data.len() {
        let id = &data[offset..offset + 4];
        let size = read_u32(data, offset + 4)? as usize;
        let start = offset + 8;
        let end = start
            .checked_add(size)
            .ok_or_else(|| "WAVチャンクサイズが不正です".to_string())?;
        if end > data.len() {
            return Err("WAVチャンクが途中で終了しています".to_string());
        }

        if id == b"fmt " {
            if size < 16 {
                return Err("WAV fmtチャンクが短すぎます".to_string());
            }
            let audio_format = read_u16(data, start)?;
            let channels = read_u16(data, start + 2)?;
            let sample_rate = read_u32(data, start + 4)?;
            let bits_per_sample = read_u16(data, start + 14)?;
            if audio_format != 1 || bits_per_sample != 16 || channels == 0 {
                return Err("16-bit PCM WAVのみ処理できます".to_string());
            }
            format = Some(WavFormat {
                channels,
                sample_rate,
            });
        } else if id == b"data" {
            if size & 1 != 0 {
                return Err("PCMデータ長が不正です".to_string());
            }
            pcm = Some(
                data[start..end]
                    .chunks_exact(2)
                    .map(|chunk| i16::from_le_bytes([chunk[0], chunk[1]]))
                    .collect(),
            );
        }

        offset = end + (size & 1);
    }

    let format = format.ok_or_else(|| "WAV fmtチャンクがありません".to_string())?;
    let pcm = pcm.ok_or_else(|| "WAV dataチャンクがありません".to_string())?;
    if pcm.len() % format.channels as usize != 0 {
        return Err("PCMサンプル数とチャンネル数が一致しません".to_string());
    }
    Ok((format, pcm))
}

fn encode_pcm16_wav(format: WavFormat, samples: &[i16]) -> Result<Vec<u8>, String> {
    let data_len = samples
        .len()
        .checked_mul(2)
        .ok_or_else(|| "PCMデータが大きすぎます".to_string())?;
    let data_len_u32 =
        u32::try_from(data_len).map_err(|_| "PCMデータが大きすぎます".to_string())?;
    let byte_rate = format
        .sample_rate
        .checked_mul(format.channels as u32)
        .and_then(|value| value.checked_mul(2))
        .ok_or_else(|| "WAVサンプルレートが不正です".to_string())?;
    let block_align = format.channels * 2;

    let mut output = Vec::with_capacity(44 + data_len);
    output.extend_from_slice(b"RIFF");
    output.extend_from_slice(&(36u32 + data_len_u32).to_le_bytes());
    output.extend_from_slice(b"WAVEfmt ");
    output.extend_from_slice(&16u32.to_le_bytes());
    output.extend_from_slice(&1u16.to_le_bytes());
    output.extend_from_slice(&format.channels.to_le_bytes());
    output.extend_from_slice(&format.sample_rate.to_le_bytes());
    output.extend_from_slice(&byte_rate.to_le_bytes());
    output.extend_from_slice(&block_align.to_le_bytes());
    output.extend_from_slice(&16u16.to_le_bytes());
    output.extend_from_slice(b"data");
    output.extend_from_slice(&data_len_u32.to_le_bytes());
    for sample in samples {
        output.extend_from_slice(&sample.to_le_bytes());
    }
    Ok(output)
}

fn process_effects(
    format: &mut WavFormat,
    samples: Vec<i16>,
    echo_level: Option<i32>,
    yamabiko_level: Option<i32>,
    panning: Option<&str>,
) -> Vec<i16> {
    let echo_enabled = echo_level.unwrap_or(0) != 0;
    let yamabiko_enabled = yamabiko_level.unwrap_or(0) != 0;
    let mut working: Vec<i32> = samples.into_iter().map(i32::from).collect();

    if echo_enabled || yamabiko_enabled {
        let delay_seconds = if echo_enabled { 0.15 } else { 0.35 };
        let delay_samples =
            (format.sample_rate as f64 * delay_seconds) as usize * format.channels as usize;
        let repetitions = if yamabiko_enabled { 3usize } else { 1usize };
        let level = if yamabiko_enabled {
            yamabiko_level.unwrap_or(0)
        } else {
            echo_level.unwrap_or(0)
        };
        let decay = (level as f64 / 100.0).clamp(0.1, 0.8);
        let mut output = vec![0i32; working.len() + delay_samples * repetitions];
        for (index, sample) in working.iter().copied().enumerate() {
            output[index] = output[index].saturating_add(sample);
            for repetition in 1..=repetitions {
                let target = index + repetition * delay_samples;
                let echo = (sample as f64 * decay.powi(repetition as i32)) as i32;
                output[target] = output[target].saturating_add(echo);
            }
        }
        working = output;
    }

    let clipped: Vec<i16> = working
        .into_iter()
        .map(|sample| sample.clamp(i16::MIN as i32, i16::MAX as i32) as i16)
        .collect();

    match (panning, format.channels) {
        (Some("left"), 1) => {
            format.channels = 2;
            clipped.into_iter().flat_map(|sample| [sample, 0]).collect()
        }
        (Some("right"), 1) => {
            format.channels = 2;
            clipped.into_iter().flat_map(|sample| [0, sample]).collect()
        }
        (Some("left"), 2) => clipped
            .chunks_exact(2)
            .flat_map(|pair| [pair[0], 0])
            .collect(),
        (Some("right"), 2) => clipped
            .chunks_exact(2)
            .flat_map(|pair| [0, pair[1]])
            .collect(),
        _ => clipped,
    }
}

fn temporary_wav_path() -> PathBuf {
    let timestamp = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_nanos();
    let sequence = TEMP_SEQUENCE.fetch_add(1, Ordering::Relaxed);
    std::env::temp_dir().join(format!(
        "livevoicebridge-{timestamp}-{}-{sequence}.wav",
        std::process::id()
    ))
}

fn process_wav_file(
    wav_path: &Path,
    echo_level: Option<i32>,
    yamabiko_level: Option<i32>,
    panning: Option<&str>,
) -> Result<PathBuf, String> {
    let input = fs::read(wav_path).map_err(|error| format!("WAV読込失敗: {error}"))?;
    let (mut format, samples) = decode_pcm16_wav(&input)?;
    let processed = process_effects(&mut format, samples, echo_level, yamabiko_level, panning);
    let encoded = encode_pcm16_wav(format, &processed)?;

    for _ in 0..16 {
        let output_path = temporary_wav_path();
        match OpenOptions::new()
            .write(true)
            .create_new(true)
            .open(&output_path)
        {
            Ok(mut file) => {
                if let Err(error) = file.write_all(&encoded) {
                    let _ = fs::remove_file(&output_path);
                    return Err(format!("WAV書込失敗: {error}"));
                }
                fs::remove_file(wav_path).map_err(|error| format!("元WAV削除失敗: {error}"))?;
                return Ok(output_path);
            }
            Err(error) if error.kind() == std::io::ErrorKind::AlreadyExists => continue,
            Err(error) => return Err(format!("一時WAV作成失敗: {error}")),
        }
    }
    Err("一時WAV名を確保できませんでした".to_string())
}

#[pyfunction]
#[pyo3(signature = (wav_path, echo_level=None, yamabiko_level=None, panning=None))]
pub fn apply_audio_effects(
    py: Python<'_>,
    wav_path: String,
    echo_level: Option<i32>,
    yamabiko_level: Option<i32>,
    panning: Option<String>,
) -> PyResult<String> {
    if echo_level.unwrap_or(0) == 0 && yamabiko_level.unwrap_or(0) == 0 && panning.is_none() {
        return Ok(wav_path);
    }
    let input = PathBuf::from(wav_path);
    let result = py.allow_threads(move || {
        process_wav_file(&input, echo_level, yamabiko_level, panning.as_deref())
    });
    result
        .map(|path| path.to_string_lossy().into_owned())
        .map_err(PyIOError::new_err)
}

#[pyfunction]
pub fn float_audio_to_wav_bytes<'py>(
    py: Python<'py>,
    samples: &Bound<'py, PyAny>,
    sample_rate: u32,
    volume: f32,
) -> PyResult<Bound<'py, PyBytes>> {
    if sample_rate == 0 {
        return Err(PyValueError::new_err(
            "sample_rateは1以上である必要があります",
        ));
    }
    let buffer = PyBuffer::<f32>::get(samples)?;
    let values = buffer.to_vec(py)?;
    let encoded = py
        .allow_threads(move || {
            let pcm: Vec<i16> = values
                .into_iter()
                .map(|sample| {
                    let scaled = if sample.is_finite() {
                        sample * volume
                    } else {
                        0.0
                    };
                    (scaled.clamp(-1.0, 1.0) * 32767.0) as i16
                })
                .collect();
            encode_pcm16_wav(
                WavFormat {
                    channels: 1,
                    sample_rate,
                },
                &pcm,
            )
        })
        .map_err(PyValueError::new_err)?;
    Ok(PyBytes::new(py, &encoded))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn pcm16_wav_round_trip() {
        let format = WavFormat {
            channels: 2,
            sample_rate: 48_000,
        };
        let samples = vec![i16::MIN, -1, 0, 1, i16::MAX, 123];
        let encoded = encode_pcm16_wav(format, &samples).unwrap();
        let (decoded_format, decoded_samples) = decode_pcm16_wav(&encoded).unwrap();
        assert_eq!(decoded_format.channels, 2);
        assert_eq!(decoded_format.sample_rate, 48_000);
        assert_eq!(decoded_samples, samples);
    }

    #[test]
    fn echo_and_left_pan_have_expected_shape() {
        let mut format = WavFormat {
            channels: 1,
            sample_rate: 100,
        };
        let output = process_effects(&mut format, vec![1000, -1000], Some(50), None, Some("left"));
        assert_eq!(format.channels, 2);
        assert_eq!(output.len(), (2 + 15) * 2);
        assert_eq!(&output[..4], &[1000, 0, -1000, 0]);
        assert_eq!(&output[30..34], &[500, 0, -500, 0]);
    }
}
