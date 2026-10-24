use std::sync::Arc;

use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;

#[derive(Clone, Copy)]
pub(crate) struct WavFormat {
    pub(crate) channels: u16,
    pub(crate) sample_rate: u32,
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

#[cfg(test)]
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
    mut samples: Vec<i16>,
    echo: Option<i32>,
    yamabiko: Option<i32>,
    panning: Option<&str>,
    max_bytes: usize,
) -> Result<Vec<i16>, String> {
    let echo_enabled = echo.unwrap_or(0) != 0;
    let yamabiko_enabled = yamabiko.unwrap_or(0) != 0;
    let effect = echo_enabled || yamabiko_enabled;
    let repetitions = if yamabiko_enabled { 3 } else { 1 };
    let channels = format.channels as usize;
    let mono_pan = channels == 1 && matches!(panning, Some("left" | "right"));
    let delay = if effect {
        ((format.sample_rate as f64 * if echo_enabled { 0.15 } else { 0.35 }) as usize)
            .checked_mul(channels)
            .ok_or("音声長が不正です。")?
    } else {
        0
    };
    let length = samples
        .len()
        .checked_add(delay.checked_mul(repetitions).ok_or("音声長が不正です。")?)
        .ok_or("音声長が不正です。")?;
    let output_len = length
        .checked_mul(if mono_pan { 2 } else { 1 })
        .ok_or("音声長が不正です。")?;
    if output_len
        .checked_mul(2)
        .is_none_or(|bytes| bytes > max_bytes)
    {
        return Err("加工後の音声が容量上限を超えました。".into());
    }
    if !effect && !mono_pan {
        if channels == 2 {
            for pair in samples.chunks_exact_mut(2) {
                match panning {
                    Some("left") => pair[1] = 0,
                    Some("right") => pair[0] = 0,
                    _ => {}
                }
            }
        }
        return Ok(samples);
    }
    let decay = (if yamabiko_enabled {
        yamabiko.unwrap_or(0)
    } else {
        echo.unwrap_or(0)
    } as f64
        / 100.0)
        .clamp(0.1, 0.8);
    let mut rates = [0.0; 3];
    for (index, rate) in rates.iter_mut().take(repetitions).enumerate() {
        *rate = decay.powi((index + 1) as i32);
    }
    let mut output = vec![0i16; output_len];
    for index in 0..length {
        let mut mixed = samples.get(index).copied().unwrap_or(0) as i32;
        if effect {
            for (repetition, rate) in rates.iter().take(repetitions).enumerate() {
                if let Some(source) = index
                    .checked_sub(delay * (repetition + 1))
                    .and_then(|position| samples.get(position))
                {
                    mixed = mixed.saturating_add((*source as f64 * rate) as i32);
                }
            }
        }
        let value = mixed.clamp(i16::MIN as i32, i16::MAX as i32) as i16;
        if mono_pan {
            output[index * 2 + usize::from(panning == Some("right"))] = value;
        } else if !matches!(
            (panning, index % channels),
            (Some("left"), 1) | (Some("right"), 0)
        ) {
            output[index] = value;
        }
    }
    if mono_pan {
        format.channels = 2;
    }
    Ok(output)
}

#[pyclass(frozen)]
#[derive(Clone)]
pub struct AudioClip {
    pub(crate) samples: Arc<Vec<i16>>,
    pub(crate) format: WavFormat,
}

#[pymethods]
impl AudioClip {
    #[staticmethod]
    #[pyo3(signature=(wav, max_bytes, echo=None, yamabiko=None, panning=None))]
    fn from_wav(
        py: Python<'_>,
        wav: &[u8],
        max_bytes: usize,
        echo: Option<i32>,
        yamabiko: Option<i32>,
        panning: Option<String>,
    ) -> PyResult<Self> {
        py.allow_threads(|| {
            if max_bytes == 0 || wav.len() > max_bytes.saturating_add(65536) {
                return Err("音声データが容量上限を超えました。".to_string());
            }
            let (mut format, samples) = decode_pcm16_wav(wav)?;
            if format.channels > 2 || format.sample_rate == 0 || samples.is_empty() {
                return Err("PCM16モノラルまたはステレオ音声が必要です。".into());
            }
            let samples = process_effects(
                &mut format,
                samples,
                echo,
                yamabiko,
                panning.as_deref(),
                max_bytes,
            )?;
            if samples.len().saturating_mul(2) > max_bytes {
                return Err("加工後の音声が容量上限を超えました。".into());
            }
            Ok(Self {
                samples: Arc::new(samples),
                format,
            })
        })
        .map_err(PyValueError::new_err)
    }

    #[getter]
    fn byte_length(&self) -> usize {
        self.samples.len() * 2
    }

    #[getter]
    fn sample_rate(&self) -> u32 {
        self.format.sample_rate
    }

    #[getter]
    fn channels(&self) -> u16 {
        self.format.channels
    }
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
        let output = process_effects(
            &mut format,
            vec![1000, -1000],
            Some(50),
            None,
            Some("left"),
            1024,
        )
        .unwrap();
        assert_eq!(format.channels, 2);
        assert_eq!(output.len(), (2 + 15) * 2);
        assert_eq!(&output[..4], &[1000, 0, -1000, 0]);
        assert_eq!(&output[30..34], &[500, 0, -500, 0]);
    }
}
