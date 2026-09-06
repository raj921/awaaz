"""Predict emotion for any Hindi / Telugu / Hinglish text.

Usage:
    .venv/bin/python research/benchmark/infer_emotion.py "text" ["more text" ...]
"""
import pickle
import sys

MODELS = pickle.load(open("data/checkpoints/emotion_models.pkl", "rb"))


def pick_language(text):
    # ponytail: script-range sniff; misses mixed-script text -- upgrade: --language flag or fasttext lid if it bites
    if any("\u0900" <= c <= "\u097f" for c in text):
        return "hi"
    if any("\u0c00" <= c <= "\u0c7f" for c in text):
        return "te"
    return "hi-en"


if not sys.argv[1:]:
    print(__doc__)
    sys.exit(1)

for arg in sys.argv[1:]:
    language = pick_language(arg)
    emotion = MODELS[language].predict([arg])[0]
    print(f"{language:<6} {emotion:<10} | {arg}")
