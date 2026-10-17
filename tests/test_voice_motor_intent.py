"""Exercise both model boundaries with controlled SDK responses."""
import io
import json
import wave
from types import SimpleNamespace as NS
import pytest
from TITI.voice_motor.intent import IntentClient, IntentError


def wav():
    out = io.BytesIO()
    with wave.open(out, 'wb') as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(16000)
        f.writeframes(b'\0\0'*8000)
    return out.getvalue()


def fake_client(text='3번 모터 위치 2200으로 이동', output=None, status='completed', content=None):
    calls = []
    def transcribe(**kw):
        calls.append(('audio', kw))
        return NS(text=text)
    def respond(**kw):
        calls.append(('llm', kw))
        return NS(status=status, output_text=output if output is not None else json.dumps({'action': 'move', 'targets': [{'motor': 3, 'position': 2200}]}), output=[NS(type='message', content=content or [])])
    return NS(audio=NS(transcriptions=NS(create=transcribe)), responses=NS(create=respond)), calls


def test_two_models_in_order_and_strict_output():
    client, calls = fake_client()
    text, command = IntentClient(client, 'voice-test', 'llm-test').from_audio(wav())
    assert text == '3번 모터 위치 2200으로 이동'
    assert command.targets[0].position == 2200
    assert [c[0] for c in calls] == ['audio', 'llm']
    assert calls[0][1]['model'] == 'voice-test'
    assert calls[0][1]['language'] == 'ko'
    assert calls[0][1]['file'][0].endswith('.wav')
    assert calls[1][1]['model'] == 'llm-test'
    assert calls[1][1]['text']['format']['strict'] is True


def test_empty_transcription_skips_llm():
    client, calls = fake_client(text='  ')
    with pytest.raises(IntentError):
        IntentClient(client, 'v', 'l').from_audio(wav())
    assert [c[0] for c in calls] == ['audio']


@pytest.mark.parametrize('params', [
    {'status': 'incomplete'}, {'output': 'not JSON'},
    {'output': '{"action":"move","targets":[{"motor":7,"position":1}]}'},
    {'content': [NS(type='refusal', refusal='refused')]},
])
def test_bad_model_result_rejected(params):
    client, _ = fake_client(**params)
    with pytest.raises(IntentError):
        IntentClient(client, 'v', 'l').from_text('3번 모터 2200')


def test_api_exception_message_does_not_echo_provider_secrets():
    client, _ = fake_client()
    def failed(**kwargs):
        raise RuntimeError('secret-provider-value')
    client.responses.create = failed
    with pytest.raises(IntentError) as error:
        IntentClient(client, 'v', 'l').from_text('3번 모터 2200')
    assert 'secret-provider-value' not in str(error.value)


def test_invalid_audio_not_sent():
    client, calls = fake_client()
    with pytest.raises(IntentError):
        IntentClient(client, 'v', 'l').from_audio(b'not a wav')
    assert calls == []
