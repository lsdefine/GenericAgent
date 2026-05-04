#!/usr/bin/env python3
"""
Voice Interface for GenericAgent
语音接口: 语音识别(STT)、语音合成(TTS)、语音命令解析、音频处理
支持: 离线/在线模式、多语言、命令意图提取、音频格式转换
"""

import os
import json
import wave
import struct
import logging
import subprocess
from datetime import datetime
from typing import Dict, List, Optional, Callable, Tuple

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)

# Common voice commands mapping
VOICE_COMMANDS = {
    'en': {
        'open': 'action_open', 'close': 'action_close', 'start': 'action_start',
        'stop': 'action_stop', 'search': 'action_search', 'send': 'action_send',
        'read': 'action_read', 'write': 'action_write', 'delete': 'action_delete',
        'help': 'action_help', 'status': 'action_status', 'save': 'action_save'
    },
    'zh': {
        '打开': 'action_open', '关闭': 'action_close', '开始': 'action_start',
        '停止': 'action_stop', '搜索': 'action_search', '发送': 'action_send',
        '读取': 'action_read', '写入': 'action_write', '删除': 'action_delete',
        '帮助': 'action_help', '状态': 'action_status', '保存': 'action_save'
    }
}

class AudioProcessor:
    def __init__(self, sample_rate: int = 16000, channels: int = 1, bit_depth: int = 16):
        self.sample_rate = sample_rate
        self.channels = channels
        self.bit_depth = bit_depth
    
    def generate_silence(self, duration_ms: int = 500) -> bytes:
        """Generate silence audio data"""
        num_samples = int(self.sample_rate * duration_ms / 1000)
        return b'\x00' * (num_samples * self.channels * (self.bit_depth // 8))
    
    def wav_to_raw(self, wav_path: str) -> bytes:
        with wave.open(wav_path, 'rb') as wf:
            return wf.readframes(wf.getnframes())
    
    def raw_to_wav(self, raw_data: bytes, output_path: str):
        with wave.open(output_path, 'wb') as wf:
            wf.setnchannels(self.channels)
            wf.setsampwidth(self.bit_depth // 8)
            wf.setframerate(self.sample_rate)
            wf.writeframes(raw_data)
    
    def get_audio_info(self, wav_path: str) -> Dict:
        with wave.open(wav_path, 'rb') as wf:
            return {
                'channels': wf.getnchannels(),
                'sample_width': wf.getsampwidth(),
                'frame_rate': wf.getframerate(),
                'num_frames': wf.getnframes(),
                'duration_sec': wf.getnframes() / wf.getframerate()
            }


class SpeechToText:
    def __init__(self, lang: str = 'en'):
        self.lang = lang
        self.model_path = None
    
    def transcribe(self, audio_path: str) -> str:
        """Transcribe audio to text (placeholder - requires external STT engine)"""
        # In production, integrate with: whisper, Google Speech API, Vosk, etc.
        return f"[STT Placeholder] Recognized audio: {os.path.basename(audio_path)}"
    
    def transcribe_stream(self, chunk: bytes) -> str:
        """Stream transcription"""
        return ""


class TextToSpeech:
    def __init__(self, lang: str = 'en', voice: str = 'default'):
        self.lang = lang
        self.voice = voice
    
    def synthesize(self, text: str, output_path: str = None) -> Optional[bytes]:
        """Synthesize text to speech (placeholder)"""
        # In production: gTTS, pyttsx3, Azure TTS, etc.
        audio_data = AudioProcessor().generate_silence(100)
        if output_path:
            AudioProcessor().raw_to_wav(audio_data, output_path)
        return audio_data
    
    def say(self, text: str):
        """Text to speech with system player"""
        # macOS
        if subprocess.call(['which', 'say'], stdout=subprocess.DEVNULL) == 0:
            subprocess.Popen(['say', '-v', self.voice, text])
        else:
            logger.info(f"[TTS] {text}")


class VoiceCommandParser:
    def __init__(self, lang: str = 'en'):
        self.lang = lang
        self.commands = VOICE_COMMANDS.get(lang, VOICE_COMMANDS['en'])
        self.intent_handlers: Dict[str, Callable] = {}
    
    def register_handler(self, action: str, handler: Callable):
        self.intent_handlers[action] = handler
    
    def parse(self, text: str) -> Dict:
        words = text.lower().split()
        detected_action = None
        target = ' '.join(words[1:]) if len(words) > 1 else ''
        
        for word in words:
            if word in self.commands:
                detected_action = self.commands[word]
                break
        
        # Try Chinese commands
        if not detected_action:
            for word in text:
                if word in self.commands:
                    detected_action = self.commands[word]
                    target = text.replace(word, '').strip()
                    break
        
        result = {
            'text': text, 'action': detected_action, 'target': target,
            'confidence': 0.9 if detected_action else 0.3,
            'timestamp': datetime.now().isoformat()
        }
        
        if detected_action and detected_action in self.intent_handlers:
            try:
                result['handler_result'] = self.intent_handlers[detected_action](target)
            except Exception as e:
                result['handler_error'] = str(e)
        
        return result


class VoiceInterface:
    def __init__(self, audio_dir: str = ".voice_data", default_lang: str = 'en'):
        self.audio_dir = audio_dir
        self.default_lang = default_lang
        self.stt = SpeechToText(default_lang)
        self.tts = TextToSpeech(default_lang)
        self.command_parser = VoiceCommandParser(default_lang)
        self.processor = AudioProcessor()
        os.makedirs(audio_dir, exist_ok=True)
    
    def record(self, duration_sec: int = 5, output_file: str = None) -> str:
        """Record audio (placeholder - requires microphone access)"""
        output_file = output_file or os.path.join(self.audio_dir, f"rec_{int(datetime.now().timestamp())}.wav")
        # In production: use pyaudio, sounddevice, etc.
        silence = self.processor.generate_silence(duration_sec * 1000)
        self.processor.raw_to_wav(silence, output_file)
        return output_file
    
    def process_voice_command(self, audio_path: str) -> Dict:
        """Full pipeline: STT -> Parse -> Execute"""
        text = self.stt.transcribe(audio_path)
        result = self.command_parser.parse(text)
        result['audio_path'] = audio_path
        result['transcribed_text'] = text
        return result
    
    def respond(self, text: str, output_file: str = None):
        """TTS response"""
        self.tts.synthesize(text, output_file)
    
    def set_language(self, lang: str):
        self.default_lang = lang
        self.stt = SpeechToText(lang)
        self.tts = TextToSpeech(lang)
        self.command_parser = VoiceCommandParser(lang)


if __name__ == '__main__':
    vi = VoiceInterface()
    
    print("=== Voice Command Parsing ===")
    tests = [
        ("en", "open the document"),
        ("en", "stop recording"),
        ("zh", "打开文件管理器"),
        ("zh", "发送邮件给张三"),
    ]
    
    for lang, cmd in tests:
        vi.set_language(lang)
        result = vi.command_parser.parse(cmd)
        print(f"[{lang}] '{cmd}' -> action: {result['action']}, target: {result['target']}")
    
    print("\n=== Audio Info ===")
    info = vi.processor.get_audio_info
    # Generate a test file
    test_wav = os.path.join(vi.audio_dir, "test.wav")
    vi.record(duration_sec=2, output_file=test_wav)
    print(json.dumps(vi.processor.get_audio_info(test_wav), indent=2))
