# Video Editor cho Codex / GitHub

Tu dong cat khoang lang, tao phu de tieng Viet va hieu ung chu don gian (motion text). **Khong phai ung dung editor co giao dien**.

## 1. Tai len GitHub
Tai len repository `moitruong` ba file: `video_editor.py`, `requirements.txt` va `.gitignore`. Neu dung file ZIP, **giai nen truoc** khi tai len GitHub.

**Quan trong:** Khong tai video rieng tu len repository Public. Noi dung chat dinh kem video **khong tu dong** nam trong folder ma Codex truy cap. Ban can cung cap file trong workspace duoc phep xu ly.

## 2. Cai dat cho Ubuntu / Codex

```bash
python --version
sudo apt-get update && sudo apt-get install -y ffmpeg fonts-noto-core
python -m pip install -r requirements.txt
python video_editor.py --check
```

Neu khong co `sudo`, yeu cau Codex cai FFmpeg theo moi truong hien co. `faster-whisper` can Internet de tai model lan dau; CPU co the xu ly cham.

## 3. Xu ly video
Dat `vid.mp4` vao folder hien tai va chay:

```bash
python video_editor.py --input vid.mp4 --output vid_edited.mp4
```

Neu khong muon cai Whisper, thu truoc phan cat khoang lang:

```bash
python video_editor.py --input vid.mp4 --output vid_cut.mp4 --no-subtitles
```

Tham so huu ich:

- `--model tiny` / `--model base`: nhe, nhanh nhung co the kem chinh xac. Mac dinh `small`.
- `--min-silence 0.8`: chi cat im lang tren 0.8 giay.
- `--silence-db -35`: nguong am thanh im lang.
- `--padding 0.18`: giu biên de khong cat mat am dau/cuoi.
- `--no-cut`: giu nguyen thoi luong video.
- `--no-motion`: tat hieu ung chu nhan manh.

## Dau ra
- `vid_edited.mp4`: video da xu ly, phu de gan vao hinh.
- `vid_edited.srt`: phu de rieng (neu co loi noi).

## Gioi han
- Chi them hieu ung chu theo tu khoa trong ban phu de, khong tu hieu/tai tao motion graphics theo hinh anh tung canh.
- Chat luong phu de phu thuoc vao am thanh va do chinh xac nhan dang. Can kiem tra thu cong.
- Chi cat khoang lang dua theo nguong am thanh, co the cat mat nhac nen rat nho / khoang dung co chu dich.
- Van phai chay tren mot moi truong co quyen truy cap video va co FFmpeg.
