#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
VIDEO EDITOR - Dung cho repository GitHub / moi truong Codex.

Cai dat (Ubuntu / Debian):
    sudo apt-get update && sudo apt-get install -y ffmpeg fonts-noto-core
    python -m pip install faster-whisper

Chay:
    python video_editor.py --input vid.mp4 --output vid_edited.mp4
    # Neu vid.mp4 cung thu muc, ban cung co the chay:
    python video_editor.py

Co the tuy chinh:
    python video_editor.py -i vid.mp4 -o ketqua.mp4 --model small \
        --silence-db -35 --min-silence 0.65

Khong tao phu de (khong can faster-whisper):
    python video_editor.py -i vid.mp4 -o ketqua.mp4 --no-subtitles

Yeu cau: Python >=3.9; ffmpeg va ffprobe (FFmpeg can co libass de ghi phu de).
Ket qua: MP4 co phu de vao hinh + file .srt (neu nhan dang duoc loi noi).
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
import textwrap
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class Caption:
    start: float
    end: float
    text: str


def run(cmd: list[str], *, capture: bool = False) -> subprocess.CompletedProcess[str]:
    print("$", " ".join(str(x) for x in cmd[:8]), "..." if len(cmd) > 8 else "", flush=True)
    return subprocess.run(cmd, text=True, capture_output=capture, check=True)


def probe(path: Path) -> dict[str, Any]:
    out = run([
        "ffprobe", "-v", "error", "-show_entries", "format=duration:stream=codec_type,width,height",
        "-of", "json", str(path)
    ], capture=True).stdout
    return json.loads(out)


def media_info(path: Path) -> tuple[float, int, int, bool]:
    data = probe(path)
    duration = float(data["format"]["duration"])
    videos = [s for s in data.get("streams", []) if s.get("codec_type") == "video"]
    if not videos:
        raise ValueError("File khong co luong hinh (video).")
    return duration, int(videos[0]["width"]), int(videos[0]["height"]), any(
        s.get("codec_type") == "audio" for s in data.get("streams", [])
    )


def detect_silences(path: Path, duration: float, noise_db: float, min_silence: float) -> list[tuple[float, float]]:
    print("[1/4] Phan tich khoang lang...")
    process = subprocess.run([
        "ffmpeg", "-hide_banner", "-nostats", "-i", str(path),
        "-af", f"silencedetect=noise={noise_db}dB:d={min_silence}",
        "-f", "null", "-"
    ], text=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, check=True)
    intervals: list[tuple[float, float]] = []
    start: float | None = None
    for line in process.stderr.splitlines():
        a = re.search(r"silence_start:\s*([-\d.]+)", line)
        b = re.search(r"silence_end:\s*([-\d.]+)", line)
        if a:
            start = max(0.0, float(a.group(1)))
        if b:
            end = min(duration, float(b.group(1)))
            if start is not None and end > start:
                intervals.append((start, end))
            start = None
    if start is not None and duration > start:
        intervals.append((start, duration))
    return intervals


def keep_ranges(silences: list[tuple[float, float]], duration: float, padding: float) -> list[tuple[float, float]]:
    # Loai bo phan giua cua nhung khoang lang; giu mot it le truoc/sau giong noi.
    unwanted = [(max(0.0, a + padding), min(duration, b - padding))
                for a, b in silences if b - a > padding * 2]
    unwanted = [(a, b) for a, b in unwanted if b - a > 0.12]
    intervals: list[tuple[float, float]] = []
    prev = 0.0
    for a, b in sorted(unwanted):
        if a > prev + 0.06:
            intervals.append((prev, a))
        prev = max(prev, b)
    if duration > prev + 0.06:
        intervals.append((prev, duration))
    # Truong hop video gan nhu im lang: giu video goc, tranh xuat file rong.
    if not intervals:
        print("Khong tim thay loi noi: giu nguyen video goc.")
        return [(0.0, duration)]
    return intervals


def cut_video(src: Path, dst: Path, intervals: list[tuple[float, float]], with_audio: bool) -> None:
    print(f"[2/4] Ghep {len(intervals)} doan video...")
    if len(intervals) > 200:
        raise RuntimeError(
            f"Video co {len(intervals)} doan phai cat: qua nhieu cho filter hien tai. "
            "Hay tang --min-silence (vi du 1.0) hoac dung --no-cut."
        )
    if len(intervals) == 1 and intervals[0][0] < 0.01:
        original_duration, *_ = media_info(src)
        if intervals[0][1] >= original_duration - 0.01:
            shutil.copy2(src, dst)
            return
    n = len(intervals)
    parts: list[str] = []
    parts.append("[0:v:0]split=" + str(n) + "".join(f"[v{i}]" for i in range(n)) + ";")
    if with_audio:
        parts.append("[0:a:0]asplit=" + str(n) + "".join(f"[a{i}]" for i in range(n)) + ";")
    for i, (start, end) in enumerate(intervals):
        parts.append(f"[v{i}]trim=start={start:.4f}:end={end:.4f},setpts=PTS-STARTPTS,scale=trunc(iw/2)*2:trunc(ih/2)*2[vc{i}];")
        if with_audio:
            parts.append(f"[a{i}]atrim=start={start:.4f}:end={end:.4f},asetpts=PTS-STARTPTS[ac{i}];")
    inputs = "".join(f"[vc{i}]" + (f"[ac{i}]" if with_audio else "") for i in range(n))
    parts.append(inputs + f"concat=n={n}:v=1:a={1 if with_audio else 0}[video]" +
                 ("[audio]" if with_audio else ""))
    with tempfile.TemporaryDirectory(prefix="editscript_") as t:
        script = Path(t) / "cuts.ffscript"
        script.write_text("\n".join(parts), encoding="utf-8")
        cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", str(src),
               "-filter_complex_script", str(script), "-map", "[video]"]
        if with_audio:
            cmd += ["-map", "[audio]"]
        cmd += ["-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p"]
        if with_audio:
            cmd += ["-c:a", "aac", "-b:a", "160k"]
        cmd += ["-movflags", "+faststart", str(dst)]
        run(cmd)


def transcribe(path: Path, model_size: str, language: str) -> list[Caption]:
    print("[3/4] Tu dong nghe va tao phu de... (lan dau can tai model)")
    try:
        from faster_whisper import WhisperModel  # type: ignore
    except ImportError as exc:
        raise RuntimeError("Chua cai faster-whisper. Chay: python -m pip install faster-whisper") from exc
    # CPU int8 mac dinh de tranh loi GPU CUDA/cuDNN cua moi truong cloud.
    # Neu muon GPU, co the tuy chinh theo tai lieu faster-whisper.
    model = WhisperModel(model_size, device="cpu", compute_type="int8")
    segments, info = model.transcribe(str(path), language=language, vad_filter=True,
                                      word_timestamps=True, beam_size=5)
    words: list[tuple[float, float, str]] = []
    for seg in segments:
        if seg.words:
            for word in seg.words:
                value = word.word.strip()
                if value:
                    words.append((max(0.0, word.start), max(word.start + 0.05, word.end), value))
        elif seg.text.strip():
            words.append((seg.start, seg.end, seg.text.strip()))
    print(f"Nhan dang ngon ngu: {info.language}; {len(words)} tu/cum tu.")
    result: list[Caption] = []
    phrase: list[str] = []
    begin = end = 0.0
    for w_start, w_end, token in words:
        if not phrase:
            begin = w_start
        elif (w_start - end > 0.58 or w_end - begin > 2.7 or
              len(phrase) >= 7 or len(" ".join(phrase) + token) > 55):
            result.append(Caption(begin, end, " ".join(phrase)))
            phrase = []
            begin = w_start
        phrase.append(token)
        end = w_end
        if re.search(r"[.!?…]$", token) and len(phrase) >= 3:
            result.append(Caption(begin, end, " ".join(phrase)))
            phrase = []
    if phrase:
        result.append(Caption(begin, end, " ".join(phrase)))
    return result


def ts_srt(seconds: float) -> str:
    ms = max(0, round(seconds * 1000))
    hh, ms = divmod(ms, 3600000)
    mm, ms = divmod(ms, 60000)
    ss, ms = divmod(ms, 1000)
    return f"{hh:02}:{mm:02}:{ss:02},{ms:03}"


def ts_ass(seconds: float) -> str:
    cs = max(0, round(seconds * 100))
    hh, cs = divmod(cs, 360000)
    mm, cs = divmod(cs, 6000)
    ss, cs = divmod(cs, 100)
    return f"{hh}:{mm:02}:{ss:02}.{cs:02}"


def safe_ass(text: str) -> str:
    return (text.replace("\\", "").replace("{", "(").replace("}", ")")
            .replace("\r", " ").replace("\n", " "))


def save_srt(captions: list[Caption], path: Path) -> None:
    path.write_text("\n".join(
        f"{i}\n{ts_srt(c.start)} --> {ts_srt(max(c.start + 0.15, c.end))}\n{c.text}\n"
        for i, c in enumerate(captions, start=1)
    ), encoding="utf-8")


# Keyword mang tinh goi y: dung lam hieu ung chu, khong thay cho phan tich noi dung video.
KEYWORDS = [
    "quan trọng", "lưu ý", "chú ý", "tóm lại", "kết luận", "đầu tiên", "thứ nhất",
    "thứ hai", "bước tiếp", "ví dụ", "kết quả", "giải pháp", "bí quyết", "mấu chốt",
    "cần nhớ", "đặc biệt", "ưu điểm", "nhược điểm"
]


def key_moments(captions: list[Caption]) -> list[tuple[float, float, str]]:
    moments = []
    last = -20.0
    for c in captions:
        if c.start - last < 7.5:
            continue
        hit = next((key for key in KEYWORDS if key in c.text.casefold()), None)
        if hit:
            moments.append((c.start, min(c.end + 0.9, c.start + 2.2), hit.upper()))
            last = c.start
    return moments[:20]


def save_ass(captions: list[Caption], path: Path, width: int, height: int, enable_motion: bool) -> None:
    portrait = height > width
    scale = height / (1920 if portrait else 1080)
    sub_size = max(24, int((55 if portrait else 48) * scale))
    pop_size = max(30, int((70 if portrait else 66) * scale))
    margin_v = max(24, int(height * (0.12 if portrait else 0.075)))
    max_chars = 25 if portrait else 43
    header = f"""[Script Info]
Title: Phu de tu dong - video_editor.py
ScriptType: v4.00+
WrapStyle: 2
ScaledBorderAndShadow: yes
PlayResX: {width}
PlayResY: {height}

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Subtitle,Noto Sans,{sub_size},&H00FFFFFF,&H0000FFFF,&H00101620,&H80000000,-1,0,0,0,100,100,0,0,1,3,1,2,30,30,{margin_v},1
Style: Pop,Noto Sans,{pop_size},&H0000E5FF,&H00000000,&H00101620,&H80000000,-1,0,0,0,100,100,0,0,1,4,1,8,40,40,{max(30, int(height * 0.13))},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    events = []
    for c in captions:
        wrapped = textwrap.wrap(safe_ass(c.text), width=max_chars, break_long_words=False,
                                break_on_hyphens=False)[:2]
        phrase = r"\N".join(wrapped)
        if not phrase:
            continue
        # Scale pop-in + fade-in; phu de hien o phia duoi.
        phrase = r"{\fad(90,120)\fscx94\fscy94\t(0,180,\fscx100\fscy100)}" + phrase
        events.append(f"Dialogue: 0,{ts_ass(c.start)},{ts_ass(max(c.end + 0.18,c.start + 0.35))},Subtitle,,0,0,0,,{phrase}")
    if enable_motion:
        for start, end, keyword in key_moments(captions):
            phrase = r"{\fad(120,180)\fscx75\fscy75\t(0,250,\fscx105\fscy105)}" + safe_ass(keyword)
            events.append(f"Dialogue: 1,{ts_ass(start)},{ts_ass(max(start + 0.8, end))},Pop,,0,0,0,,{phrase}")
    path.write_text(header + "\n".join(events) + "\n", encoding="utf-8")


def burn_subtitles(src: Path, dst: Path, ass: Path) -> None:
    print("[4/4] Render video va ghi phu de/chu dong len khung hinh...")
    run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", str(src),
         "-vf", "ass=" + str(ass) + ",scale=trunc(iw/2)*2:trunc(ih/2)*2", "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
         "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "160k", "-movflags",
         "+faststart", str(dst)])


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Video editor v2: cat khoang lang + phu de tieng Viet + motion text; xuat MP4."
    )
    parser.add_argument("-i", "--input", type=Path, default=Path("vid.mp4"), help="Video dau vao (mac dinh vid.mp4)")
    parser.add_argument("--check", action="store_true", help="Kiem tra moi truong truoc khi chay")
    parser.add_argument("-o", "--output", type=Path, default=Path("vid_edited.mp4"))
    parser.add_argument("--model", default="small", help="Whisper model: tiny, base, small, medium...")
    parser.add_argument("--language", default="vi", help="Ma ngon ngu, mac dinh vi")
    parser.add_argument("--silence-db", type=float, default=-35.0, help="Nguong am luong im lang (dB)")
    parser.add_argument("--min-silence", type=float, default=0.65, help="Khoang lang toi thieu (giay)")
    parser.add_argument("--padding", type=float, default=0.18, help="Giu viền khoang lang quanh loi noi")
    parser.add_argument("--no-cut", action="store_true", help="Khong cat khoang lang")
    parser.add_argument("--no-subtitles", action="store_true", help="Khong tao phu de")
    parser.add_argument("--no-motion", action="store_true", help="Tat hieu ung chu nhan manh")
    args = parser.parse_args()
    if args.check:
        import importlib.util
        ffmpeg = shutil.which("ffmpeg")
        ffprobe = shutil.which("ffprobe")
        whisper = importlib.util.find_spec("faster_whisper") is not None
        print("KIEM TRA MOI TRUONG:")
        print(" - FFmpeg:        ", "OK" if ffmpeg else "THIEU")
        print(" - FFprobe:       ", "OK" if ffprobe else "THIEU")
        print(" - faster-whisper:", "OK" if whisper else "THIEU (pip install faster-whisper)")
        if ffmpeg:
            filters = run(["ffmpeg", "-hide_banner", "-filters"], capture=True).stdout
            print(" - Phu de ASS:    ", "OK" if re.search(r"\sass\s", filters) else "FFmpeg chua co filter ass/libass")
        print(" - Video vid.mp4: ", "OK" if Path("vid.mp4").is_file() else "Chua co o thu muc hien tai")
        return 0 if (ffmpeg and ffprobe) else 1
    src = args.input.expanduser().resolve()
    dst = args.output.expanduser().resolve()
    if not src.is_file():
        raise FileNotFoundError(
            f"Khong tim thay video: {src}\n"
            "Hay tai file vid.mp4 vao thu muc dang chay, hoac truyen --input /duong/dan/video.mp4. "
            "Luu y: file trong cua so chat KHONG tu dong xuat hien trong repository GitHub."
        )
    if src == dst:
        raise ValueError("Video dau vao va dau ra phai khac nhau de bao ve file goc.")
    for app in ("ffmpeg", "ffprobe"):
        if not shutil.which(app):
            raise RuntimeError(f"Thieu {app}. Ubuntu: sudo apt-get install ffmpeg")
    if args.min_silence <= 0 or args.padding < 0:
        raise ValueError("--min-silence phai > 0 va --padding phai >= 0")
    if not args.no_subtitles:
        import importlib.util
        if importlib.util.find_spec("faster_whisper") is None:
            raise RuntimeError(
                "Chua cai thu vien tao phu de 'faster-whisper'.\n"
                "Cai bang: python -m pip install -r requirements.txt\n"
                "Hoac neu chi can cat video: python video_editor.py --no-subtitles"
            )
    duration, width, height, audio = media_info(src)
    if duration <= 0:
        raise ValueError("Video co thoi luong khong hop le.")
    if not audio and not args.no_subtitles:
        print("Video khong co am thanh: khong the nhan dang giong noi. Bo qua phu de.")
        args.no_subtitles = True
    dst.parent.mkdir(parents=True, exist_ok=True)
    print(f"Dau vao: {src.name} | {duration:.1f}s | {width}x{height} | Audio: {audio}")
    with tempfile.TemporaryDirectory(prefix="auto_video_") as temp:
        cut = Path(temp) / "cut.mp4"
        if audio and not args.no_cut:
            silences = detect_silences(src, duration, args.silence_db, args.min_silence)
            intervals = keep_ranges(silences, duration, args.padding)
            print(f"Giu lai {sum(b - a for a, b in intervals):.1f}/{duration:.1f} giay")
            cut_video(src, cut, intervals, with_audio=True)
        else:
            print("[1-2/4] Bo qua cat khoang lang.")
            shutil.copy2(src, cut)
        if args.no_subtitles:
            print("[3-4/4] Khong tao phu de; xuat file MP4.")
            shutil.copy2(cut, dst)
        else:
            captions = transcribe(cut, args.model, args.language)
            if not captions:
                print("Khong nhan dang duoc loi noi; xuat video khong phu de.")
                shutil.copy2(cut, dst)
            else:
                subtitle_file = dst.with_suffix(".srt")
                save_srt(captions, subtitle_file)
                _, w, h, _ = media_info(cut)
                ass = Path(temp) / "captions.ass"
                save_ass(captions, ass, w, h, enable_motion=not args.no_motion)
                burn_subtitles(cut, dst, ass)
                print("Da tao SRT:", subtitle_file)
    print("HOAN THANH:", dst)
    print("Ghi chu: hieu ung chu duoc chon theo tu khoa trong loi noi;"
          " chua tu hieu cac diem nhan ve hinh anh cua video.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (subprocess.CalledProcessError, OSError, RuntimeError, ValueError) as exc:
        print("LOI:", exc, file=sys.stderr)
        sys.exit(1)
