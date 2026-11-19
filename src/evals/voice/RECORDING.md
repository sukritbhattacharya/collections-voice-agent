# Recording the speech-recognition test clips

Twenty short clips, about ten minutes of work. These measure whether Deepgram
survives the way customers actually speak — Hindi and English mixed inside one
sentence, with amounts in Hindi numerals.

## Why a human has to record these

Synthesising the audio would test one vendor's text-to-speech against another
vendor's speech-to-text. It would produce a number, and the number would mean
nothing about real callers.

## How

1. Open Voice Memos (or any recorder).
2. Read line `say:` from `ground_truth.yaml`, one clip per utterance.
3. Speak normally — phone-call pace, no enunciating for the microphone. If you
   would say it quickly on a real call, say it quickly here.
4. Save each as its id: `01`, `02`, … `20`.
5. Drop them in `src/evals/voice/audio/`.

`.m4a`, `.wav`, `.mp3` and `.ogg` all work; the harness converts.

## What matters

Record them the way a customer in a hurry would, not the way you would read a
sentence aloud to a machine. The clips that matter most are 01–07: if "saat"
(seven) and "saath" (sixty) come back confused, the agent records the wrong
commitment, and that is exactly the kind of failure worth finding before a
customer does.

Background noise is fine. Real calls have it.
