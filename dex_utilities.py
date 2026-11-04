#!/usr/bin/env python3
"""
Dex's Utilities
  1) Baixar vídeos de links (yt-dlp)
  2) Baixar galerias / GIFs / imagens (gallery-dl, ex.: Kemono)
  3) Preparar vídeo para status do WhatsApp (ffmpeg)
  4) Identificar música, estilo Shazam (shazamio)
"""
import os
import re
import shutil
import subprocess
import sys
import threading
import webbrowser
import urllib.request
import zipfile
from pathlib import Path

APP_NAME = "Dex's Utilities"
APP_VERSION = 4
IS_WIN = os.name == "nt"
NO_WINDOW = subprocess.CREATE_NO_WINDOW if IS_WIN else 0
FFMPEG_URLS = [
    "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip",
    "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-win64-gpl.zip",
]
APP_DATA = Path(os.environ.get("LOCALAPPDATA", Path.home() / ".local/share")) / "DexUtilities"


# --------------------------------------------------------------------------- #
#  Utilidades gerais
# --------------------------------------------------------------------------- #
def resource(name: str) -> Path:
    """Caminho de um arquivo embutido (funciona no .exe e no Python normal)."""
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    return base / name


def default_dir() -> Path:
    d = Path.home() / "Downloads" / "Dex's Utilities"
    d.mkdir(parents=True, exist_ok=True)
    return d


def run_cmd(cmd, log):
    """Roda um comando e manda cada linha de saída para log()."""
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                         stdin=subprocess.DEVNULL, creationflags=NO_WINDOW)
    for raw in p.stdout:
        line = raw.decode("utf-8", "replace").rstrip()
        if line:
            log(line)
    return p.wait()


def find_ffmpeg():
    """Procura o ffmpeg: na pasta do app, no AppData ou no PATH."""
    exe = "ffmpeg.exe" if IS_WIN else "ffmpeg"
    for folder in (Path(sys.executable).parent, APP_DATA / "ffmpeg"):
        if (folder / exe).exists():
            return str(folder / exe)
    return shutil.which("ffmpeg")


def _baixar_arquivo(url, destino, log):
    """Baixa um arquivo grande usando os certificados do certifi (evita erro de SSL)."""
    import ssl
    try:
        import certifi
        ctx = ssl.create_default_context(cafile=certifi.where())
    except Exception:
        ctx = ssl.create_default_context()
    last = -10
    with urllib.request.urlopen(url, context=ctx, timeout=60) as r, open(destino, "wb") as out:
        total = int(r.headers.get("Content-Length") or 0)
        feito = 0
        while True:
            chunk = r.read(1 << 20)
            if not chunk:
                break
            out.write(chunk)
            feito += len(chunk)
            if total:
                pct = feito * 100 // total
                if pct >= last + 10:
                    last = pct
                    log(f"  ffmpeg: {min(pct, 100)}%")


def ensure_ffmpeg(log):
    """Garante que o ffmpeg existe; no Windows baixa sozinho na primeira vez."""
    path = find_ffmpeg()
    if path:
        return path
    if not IS_WIN:
        raise RuntimeError("ffmpeg não encontrado. Instale-o (ex.: sudo apt install ffmpeg).")
    log("Primeiro uso: baixando o ffmpeg (~80 MB), isso só acontece uma vez...")
    dest = APP_DATA / "ffmpeg"
    dest.mkdir(parents=True, exist_ok=True)
    zpath = APP_DATA / "ffmpeg.zip"
    for url in FFMPEG_URLS:
        try:
            _baixar_arquivo(url, zpath, log)
            break
        except Exception as e:  # noqa: BLE001
            log(f"Falha ao baixar de {url.split('/')[2]}: {e}")
    else:
        raise RuntimeError("Não consegui baixar o ffmpeg. Abra o Prompt de Comando, rode "
                           "'winget install ffmpeg', feche e abra o programa de novo.")
    with zipfile.ZipFile(zpath) as z:
        for member in z.namelist():
            if member.endswith("bin/ffmpeg.exe"):
                with z.open(member) as src, open(dest / "ffmpeg.exe", "wb") as out:
                    shutil.copyfileobj(src, out)
                break
        else:
            raise RuntimeError("ffmpeg.exe não encontrado no arquivo baixado.")
    zpath.unlink(missing_ok=True)
    log("ffmpeg instalado.")
    return str(dest / "ffmpeg.exe")


# --------------------------------------------------------------------------- #
#  1) Baixar vídeos (yt-dlp)
# --------------------------------------------------------------------------- #
def baixar_video(link, pasta, so_audio, cookies, log, progress):
    import yt_dlp

    ffmpeg = ensure_ffmpeg(log)

    class L:
        def debug(self, m):
            if not m.startswith("[debug]"):
                pass
        def info(self, m): log(m)
        def warning(self, m): log("Aviso: " + m)
        def error(self, m): log("Erro: " + m)

    def hook(d):
        if d["status"] == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate")
            if total:
                progress(d["downloaded_bytes"] * 100 / total)
        elif d["status"] == "finished":
            progress(100)

    opts = {
        "outtmpl": str(Path(pasta) / "%(title).150B [%(id)s].%(ext)s"),
        "noplaylist": True,
        "retries": 10,
        "fragment_retries": 10,
        "concurrent_fragment_downloads": 4,
        "ffmpeg_location": str(Path(ffmpeg).parent),
        "logger": L(),
        "progress_hooks": [hook],
        "noprogress": True,
    }
    if so_audio:
        opts["format"] = "bestaudio/best"
        opts["postprocessors"] = [{"key": "FFmpegExtractAudio",
                                   "preferredcodec": "mp3", "preferredquality": "0"}]
    else:
        opts["format"] = "bv*+ba/b"
        opts["merge_output_format"] = "mp4"
    if cookies and cookies != "nenhum":
        opts["cookiesfrombrowser"] = (cookies,)

    with yt_dlp.YoutubeDL(opts) as ydl:
        ydl.download([link])
    log("Pronto! Download concluído.")


# --------------------------------------------------------------------------- #
#  2) Baixar galerias / GIFs (gallery-dl, rodando como subprocesso do próprio app)
# --------------------------------------------------------------------------- #
def baixar_galeria(link, pasta, log):
    if getattr(sys, "frozen", False):
        cmd = [sys.executable, "--gallery-dl"]
    else:
        exe = sys.executable
        if exe.lower().endswith("pythonw.exe"):  # usa o python com console oculto, para ler a saída
            exe = exe[:-len("pythonw.exe")] + "python.exe"
        cmd = [exe, os.path.abspath(__file__), "--gallery-dl"]
    cmd += ["-d", str(pasta), link]
    code = run_cmd(cmd, log)
    log("Pronto! Download concluído." if code == 0
        else f"O gallery-dl terminou com código {code}. Veja as mensagens acima.")


def _gallery_dl_main():
    if sys.stdout is None or sys.stderr is None:  # exe sem console
        try:
            sys.stdout = open(1, "w", encoding="utf-8", closefd=False)
            sys.stderr = open(2, "w", encoding="utf-8", closefd=False)
        except OSError:
            sys.stdout = sys.stderr = open(os.devnull, "w")
    import gallery_dl
    sys.argv = ["gallery-dl"] + sys.argv[2:]
    gallery_dl.main()


# --------------------------------------------------------------------------- #
#  3) Preparar vídeo para status do WhatsApp (ffmpeg)
# --------------------------------------------------------------------------- #
def duracao_video(ffmpeg, arquivo):
    p = subprocess.run([ffmpeg, "-i", str(arquivo)], capture_output=True,
                       stdin=subprocess.DEVNULL, creationflags=NO_WINDOW)
    m = re.search(r"Duration:\s*(\d+):(\d+):([\d.]+)", p.stderr.decode("utf-8", "replace"))
    if not m:
        raise RuntimeError("Não consegui ler a duração do vídeo.")
    h, mi, s = m.groups()
    return int(h) * 3600 + int(mi) * 60 + float(s)


def preparar_status(arquivo, tela_cheia, duracao, tamanho_mb, log):
    ffmpeg = ensure_ffmpeg(log)
    arquivo = Path(arquivo)
    pasta = arquivo.with_name(arquivo.stem + "_status")
    pasta.mkdir(exist_ok=True)

    seg = min(duracao, duracao_video(ffmpeg, arquivo))
    total_kbps = int(tamanho_mb * 8 * 1024 / seg * 0.95)
    video_kbps = max(total_kbps - 128, 500)

    if tela_cheia:
        vf = ("split=2[bg][fg];"
              "[bg]scale=720:1280:force_original_aspect_ratio=increase,crop=720:1280,boxblur=30:5[b];"
              "[fg]scale=720:1280:force_original_aspect_ratio=decrease:force_divisible_by=2[f];"
              "[b][f]overlay=(W-w)/2:(H-h)/2,setsar=1")
    else:
        vf = "scale=1280:1280:force_original_aspect_ratio=decrease:force_divisible_by=2"

    cmd = [
        ffmpeg, "-y", "-hide_banner", "-loglevel", "error", "-i", str(arquivo),
        "-vf", vf, "-fps_mode", "passthrough",
        "-c:v", "libx264", "-profile:v", "high", "-pix_fmt", "yuv420p",
        "-preset", "slow", "-crf", "18",
        "-maxrate", f"{video_kbps}k", "-bufsize", f"{video_kbps * 2}k",
        "-c:a", "aac", "-b:a", "128k", "-ar", "44100",
        "-movflags", "+faststart",
        "-force_key_frames", f"expr:gte(t,n_forced*{duracao})",
        "-f", "segment", "-segment_time", str(duracao), "-reset_timestamps", "1",
        str(pasta / "parte_%02d.mp4"),
    ]
    log(f"Processando (partes de até {duracao}s, ~{video_kbps} kbps)... isso pode demorar.")
    code = run_cmd(cmd, log)
    if code != 0:
        raise RuntimeError("O ffmpeg falhou ao processar o vídeo.")
    for f in sorted(pasta.glob("parte_*.mp4")):
        log(f"  {f.name}  {f.stat().st_size / 1024 / 1024:.1f} MB")
    log(f"Pronto! Arquivos em: {pasta}")
    return pasta


# --------------------------------------------------------------------------- #
#  4) Identificar música (estilo Shazam)
# --------------------------------------------------------------------------- #
AVISO_LIBS = ("Esta função usa bibliotecas novas que ainda não estão no seu .exe.\n"
              "Rode o build.bat do zip mais recente (só uma vez) e abra o programa de novo.")


def _rms(x):
    import numpy as np
    return float(np.sqrt(np.mean(np.square(x)))) if len(x) else 0.0


def _wav_bytes(mono_int16, rate):
    import io
    import wave
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(mono_int16.tobytes())
    return buf.getvalue()


def capturar_audio(fonte, segundos, progress, log):
    """Grava o som do computador (loopback do Windows) ou do microfone."""
    import time
    import numpy as np
    import pyaudiowpatch as pyaudio

    pa = pyaudio.PyAudio()
    quadros = []
    try:
        dev = pa.get_default_wasapi_loopback() if fonte == "computador" \
            else pa.get_default_input_device_info()
        rate = int(dev["defaultSampleRate"])
        canais = max(1, min(int(dev["maxInputChannels"]), 2))
        log(f"Ouvindo por {segundos}s: {dev['name']}")

        def callback(in_data, frame_count, time_info, status):
            quadros.append(in_data)
            return (None, pyaudio.paContinue)

        stream = pa.open(format=pyaudio.paInt16, channels=canais, rate=rate, input=True,
                         input_device_index=dev["index"], frames_per_buffer=1024,
                         stream_callback=callback)
        inicio = time.time()
        while time.time() - inicio < segundos:
            progress((time.time() - inicio) * 100 / segundos)
            time.sleep(0.1)
        stream.stop_stream()
        stream.close()
    finally:
        pa.terminate()
    if not quadros:
        raise RuntimeError("Não captei nenhum som. Dê play na música e tente de novo.")
    audio = np.frombuffer(b"".join(quadros), dtype=np.int16)
    return audio.reshape(-1, canais), rate


def audio_de_arquivo(arquivo, log, max_seg=120):
    import numpy as np
    ffmpeg = ensure_ffmpeg(log)
    p = subprocess.run([ffmpeg, "-v", "error", "-i", str(arquivo), "-vn", "-t", str(max_seg),
                        "-ac", "2", "-ar", "44100", "-f", "s16le", "-"],
                       capture_output=True, stdin=subprocess.DEVNULL, creationflags=NO_WINDOW)
    audio = np.frombuffer(p.stdout, dtype=np.int16)
    if len(audio) < 44100 * 2:
        raise RuntimeError("Não consegui extrair áudio desse arquivo.")
    return audio[: len(audio) // 2 * 2].reshape(-1, 2), 44100


def gerar_trechos(audio, rate, janela=8, passo=3, max_janelas=8):
    """Corta em janelas que se sobrepõem. Para cada uma gera a mixagem normal e, se
    for estéreo, uma versão com o centro cancelado (onde costuma ficar a voz do meme)."""
    import numpy as np
    n, canais = audio.shape
    j, p = int(janela * rate), int(passo * rate)
    inicios = list(range(0, max(n - j, 0) + 1, p)) or [0]
    if len(inicios) > max_janelas:
        idx = np.linspace(0, len(inicios) - 1, max_janelas).astype(int)
        inicios = [inicios[i] for i in idx]

    def norm(x):
        pico = float(np.max(np.abs(x))) or 1.0
        return (x / pico * 0.9 * 32767).astype(np.int16)

    trechos = []
    for ini in inicios:
        seg = audio[ini: ini + j].astype(np.float32)
        if len(seg) < rate * 3:
            continue
        mid = seg.mean(axis=1)
        if _rms(mid) < 30:  # silêncio
            continue
        trechos.append(("mix", ini / rate, norm(mid)))
        if canais == 2:
            side = (seg[:, 0] - seg[:, 1]) / 2
            if _rms(side) > 0.15 * _rms(mid):
                trechos.append(("sem voz central", ini / rate, norm(side)))
    return trechos


async def _reconhecer(trechos, rate, log):
    from shazamio import Shazam
    sh = Shazam()
    votos, falhas = {}, 0
    for tipo, t0, sinal in trechos:
        try:
            r = await sh.recognize(_wav_bytes(sinal, rate))
        except Exception as e:  # noqa: BLE001
            falhas += 1
            log(f"  {t0:4.0f}s ({tipo}): falhou ({type(e).__name__})")
            continue
        faixa = r.get("track")
        if not faixa:
            log(f"  {t0:4.0f}s ({tipo}): nada")
            continue
        chave = faixa.get("key") or faixa.get("title")
        log(f"  {t0:4.0f}s ({tipo}): {faixa.get('subtitle', '?')} - {faixa.get('title', '?')}")
        info = votos.setdefault(chave, {"n": 0, "faixa": faixa})
        info["n"] += 1
    try:
        await sh.close()
    except Exception:  # noqa: BLE001
        pass
    if falhas == len(trechos):
        raise RuntimeError("Não consegui falar com o serviço de reconhecimento. "
                           "Verifique a internet e tente de novo.")
    if not votos:
        return None
    melhor = max(votos.values(), key=lambda v: v["n"])
    f = melhor["faixa"]
    return {"titulo": f.get("title", "?"), "artista": f.get("subtitle", "?"),
            "url": f.get("url", ""), "votos": melhor["n"], "total": len(trechos) - falhas,
            "outros": [(v["faixa"].get("subtitle", "?"), v["faixa"].get("title", "?"), v["n"])
                       for v in votos.values() if v is not melhor]}


def identificar_musica(fonte, arquivo, segundos, log, progress, mostrar):
    import asyncio
    try:
        import numpy  # noqa: F401
        import shazamio  # noqa: F401
        if fonte != "arquivo":
            import pyaudiowpatch  # noqa: F401
    except ImportError:
        raise RuntimeError(AVISO_LIBS)

    if fonte == "arquivo":
        audio, rate = audio_de_arquivo(arquivo, log)
    else:
        audio, rate = capturar_audio(fonte, segundos, progress, log)
    trechos = gerar_trechos(audio, rate)
    if not trechos:
        raise RuntimeError("Não captei som suficiente. Aumente o volume e tente de novo.")
    log(f"Analisando {len(trechos)} trechos...")
    resultado = asyncio.run(_reconhecer(trechos, rate, log))
    mostrar(resultado)


# --------------------------------------------------------------------------- #
#  Interface
# --------------------------------------------------------------------------- #
def run_gui():
    if sys.stdout is None:  # exe sem console
        sys.stdout = open(os.devnull, "w")
    if sys.stderr is None:
        sys.stderr = open(os.devnull, "w")
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk
    from PIL import Image, ImageTk

    BG, CARD, FG, MUTED, ACCENT = "#0b1220", "#121b2e", "#e8f0ff", "#8ea3c7", "#2f8cff"

    root = tk.Tk()
    root.withdraw()
    root.title(APP_NAME)
    root.configure(bg=BG)
    root.geometry("780x640")
    root.minsize(700, 560)
    try:
        root.iconbitmap(str(resource("icon.ico")))
    except Exception:
        pass

    logo = Image.open(resource("icon.png")).convert("RGBA")
    logo_small = ImageTk.PhotoImage(logo.resize((40, 40), Image.LANCZOS))
    logo_big = ImageTk.PhotoImage(logo.resize((150, 150), Image.LANCZOS))

    # ---- estilo ----
    st = ttk.Style(root)
    st.theme_use("clam")
    st.configure(".", background=BG, foreground=FG, fieldbackground=CARD, font=("Segoe UI", 10))
    st.configure("TNotebook", background=BG, borderwidth=0)
    st.configure("TNotebook.Tab", background=CARD, foreground=MUTED, padding=(18, 8), borderwidth=0)
    st.map("TNotebook.Tab", background=[("selected", ACCENT)], foreground=[("selected", "#ffffff")])
    st.configure("TFrame", background=BG)
    st.configure("TLabel", background=BG, foreground=FG)
    st.configure("Muted.TLabel", foreground=MUTED)
    st.configure("TEntry", fieldbackground=CARD, foreground=FG, insertcolor=FG, bordercolor=CARD)
    st.configure("TRadiobutton", background=BG, foreground=FG)
    st.map("TRadiobutton", background=[("active", BG)])
    st.configure("TCheckbutton", background=BG, foreground=FG)
    st.map("TCheckbutton", background=[("active", BG)])
    st.configure("TButton", background=CARD, foreground=FG, padding=8, borderwidth=0)
    st.map("TButton", background=[("active", "#1b2a47")])
    st.configure("Accent.TButton", background=ACCENT, foreground="#ffffff", padding=10,
                 font=("Segoe UI", 10, "bold"))
    st.map("Accent.TButton", background=[("active", "#4aa0ff"), ("disabled", "#27406b")])
    st.configure("TCombobox", fieldbackground=CARD, background=CARD, foreground=FG)
    st.configure("Horizontal.TProgressbar", background=ACCENT, troughcolor=CARD, borderwidth=0)

    # ---- cabeçalho ----
    head = ttk.Frame(root)
    head.pack(fill="x", padx=18, pady=(14, 6))
    tk.Label(head, image=logo_small, bg=BG).pack(side="left")
    ttk.Label(head, text=APP_NAME, font=("Segoe UI", 18, "bold")).pack(side="left", padx=10)
    ttk.Label(head, text=f"v{APP_VERSION}", style="Muted.TLabel").pack(side="left", pady=(8, 0))

    nb = ttk.Notebook(root)
    nb.pack(fill="both", expand=True, padx=18, pady=(4, 6))

    # ---- log compartilhado ----
    log_box = tk.Text(root, height=9, bg=CARD, fg=FG, relief="flat", wrap="word",
                      font=("Consolas", 9), state="disabled", padx=8, pady=6)
    log_box.pack(fill="x", padx=18, pady=(0, 6))
    bar = ttk.Progressbar(root, mode="determinate", maximum=100)
    bar.pack(fill="x", padx=18, pady=(0, 14))

    def log(msg):
        def _do():
            log_box.configure(state="normal")
            log_box.insert("end", msg + "\n")
            log_box.see("end")
            log_box.configure(state="disabled")
        root.after(0, _do)

    def progress(v):
        root.after(0, lambda: (bar.stop(), bar.configure(mode="determinate"), bar.configure(value=v)))

    def busy(on):
        def _do():
            if on:
                bar.configure(mode="indeterminate")
                bar.start(12)
            else:
                bar.stop()
                bar.configure(mode="determinate", value=0)
            for b in buttons:
                b.configure(state="disabled" if on else "normal")
        root.after(0, _do)

    buttons = []

    def worker(fn, *args):
        def run():
            busy(True)
            try:
                fn(*args)
            except Exception as e:  # noqa: BLE001
                log(f"Erro: {e}")
            finally:
                busy(False)
        threading.Thread(target=run, daemon=True).start()

    def folder_row(parent, var):
        row = ttk.Frame(parent)
        ttk.Entry(row, textvariable=var).pack(side="left", fill="x", expand=True)
        ttk.Button(row, text="Escolher...",
                   command=lambda: var.set(filedialog.askdirectory() or var.get())).pack(side="left", padx=(8, 0))
        return row

    # ---- aba 1: vídeos ----
    t1 = ttk.Frame(nb, padding=16)
    nb.add(t1, text="  Baixar vídeos  ")
    ttk.Label(t1, text="Link do vídeo (YouTube, TikTok, Instagram, X, Reddit, Twitch...)").pack(anchor="w")
    v_link = tk.StringVar()
    ttk.Entry(t1, textvariable=v_link).pack(fill="x", pady=(4, 12))
    ttk.Label(t1, text="Salvar em").pack(anchor="w")
    v_dir1 = tk.StringVar(value=str(default_dir()))
    folder_row(t1, v_dir1).pack(fill="x", pady=(4, 12))
    opt = ttk.Frame(t1)
    opt.pack(fill="x", pady=(0, 14))
    v_audio = tk.BooleanVar()
    ttk.Checkbutton(opt, text="Só áudio (MP3)", variable=v_audio).pack(side="left")
    ttk.Label(opt, text="Login do navegador:", style="Muted.TLabel").pack(side="left", padx=(24, 6))
    v_cookie = tk.StringVar(value="nenhum")
    ttk.Combobox(opt, textvariable=v_cookie, state="readonly", width=10,
                 values=["nenhum", "chrome", "firefox", "edge", "brave", "opera"]).pack(side="left")

    def go1():
        link = v_link.get().strip()
        if not link:
            return messagebox.showwarning(APP_NAME, "Cole o link do vídeo.")
        worker(baixar_video, link, v_dir1.get(), v_audio.get(), v_cookie.get(), log, progress)

    b1 = ttk.Button(t1, text="Baixar", style="Accent.TButton", command=go1)
    b1.pack(anchor="w")
    buttons.append(b1)

    # ---- aba 2: galerias ----
    t2 = ttk.Frame(nb, padding=16)
    nb.add(t2, text="  Galerias / GIFs  ")
    ttk.Label(t2, text="Link do post ou da página (Kemono e outros sites de galeria)").pack(anchor="w")
    g_link = tk.StringVar()
    ttk.Entry(t2, textvariable=g_link).pack(fill="x", pady=(4, 12))
    ttk.Label(t2, text="Salvar em").pack(anchor="w")
    v_dir2 = tk.StringVar(value=str(default_dir()))
    folder_row(t2, v_dir2).pack(fill="x", pady=(4, 14))

    def go2():
        link = g_link.get().strip()
        if not link:
            return messagebox.showwarning(APP_NAME, "Cole o link.")
        worker(baixar_galeria, link, v_dir2.get(), log)

    b2 = ttk.Button(t2, text="Baixar", style="Accent.TButton", command=go2)
    b2.pack(anchor="w")
    buttons.append(b2)

    # ---- aba 3: status do WhatsApp ----
    t3 = ttk.Frame(nb, padding=16)
    nb.add(t3, text="  Status do WhatsApp  ")
    ttk.Label(t3, text="Vídeo").pack(anchor="w")
    s_file = tk.StringVar()
    row = ttk.Frame(t3)
    row.pack(fill="x", pady=(4, 12))
    ttk.Entry(row, textvariable=s_file).pack(side="left", fill="x", expand=True)
    ttk.Button(row, text="Escolher...", command=lambda: s_file.set(
        filedialog.askopenfilename(filetypes=[("Vídeos", "*.mp4 *.mov *.mkv *.avi *.webm *.m4v"),
                                              ("Todos", "*.*")]) or s_file.get())).pack(side="left", padx=(8, 0))
    s_full = tk.BooleanVar(value=True)
    ttk.Checkbutton(t3, text="Preencher a tela inteira (9:16) com fundo desfocado, sem esticar",
                    variable=s_full).pack(anchor="w", pady=(0, 10))
    o3 = ttk.Frame(t3)
    o3.pack(fill="x", pady=(0, 14))
    ttk.Label(o3, text="Duração máx. por parte (s):", style="Muted.TLabel").pack(side="left")
    s_dur = tk.StringVar(value="90")
    ttk.Entry(o3, textvariable=s_dur, width=5).pack(side="left", padx=(6, 20))
    ttk.Label(o3, text="Tamanho máx. (MB):", style="Muted.TLabel").pack(side="left")
    s_mb = tk.StringVar(value="16")
    ttk.Entry(o3, textvariable=s_mb, width=5).pack(side="left", padx=6)

    def go3():
        f = s_file.get().strip()
        if not f or not Path(f).exists():
            return messagebox.showwarning(APP_NAME, "Escolha um vídeo válido.")
        try:
            dur, mb = int(s_dur.get()), float(s_mb.get().replace(",", "."))
        except ValueError:
            return messagebox.showwarning(APP_NAME, "Duração e tamanho precisam ser números.")
        worker(preparar_status, f, s_full.get(), dur, mb, log)

    b3 = ttk.Button(t3, text="Preparar vídeo", style="Accent.TButton", command=go3)
    b3.pack(anchor="w")
    buttons.append(b3)
    ttk.Label(t3, text="As partes ficam numa pasta ao lado do vídeo original. Envie-as em ordem pelo celular.",
              style="Muted.TLabel", wraplength=640).pack(anchor="w", pady=(12, 0))

    # ---- aba 4: identificar música ----
    t4 = ttk.Frame(nb, padding=16)
    nb.add(t4, text="  Identificar música  ")
    ttk.Label(t4, text="De onde vem o som?").pack(anchor="w")
    m_src = tk.StringVar(value="computador")
    for txt, val in (("Som que está tocando no computador (melhor para memes e vídeos)", "computador"),
                     ("Microfone (música tocando em outro aparelho)", "microfone"),
                     ("Um arquivo de vídeo/áudio que eu já tenho", "arquivo")):
        ttk.Radiobutton(t4, text=txt, value=val, variable=m_src).pack(anchor="w", pady=1)
    mrow = ttk.Frame(t4)
    mrow.pack(fill="x", pady=(8, 8))
    m_file = tk.StringVar()
    ttk.Entry(mrow, textvariable=m_file).pack(side="left", fill="x", expand=True)
    ttk.Button(mrow, text="Arquivo...", command=lambda: (m_file.set(
        filedialog.askopenfilename(filetypes=[("Vídeo/áudio", "*.mp4 *.mov *.mkv *.webm *.mp3 *.wav *.m4a *.ogg"),
                                              ("Todos", "*.*")]) or m_file.get()),
        m_src.set("arquivo"))).pack(side="left", padx=(8, 0))
    mdur = ttk.Frame(t4)
    mdur.pack(fill="x", pady=(0, 10))
    ttk.Label(mdur, text="Tempo de escuta (s):", style="Muted.TLabel").pack(side="left")
    m_dur = tk.StringVar(value="15")
    ttk.Entry(mdur, textvariable=m_dur, width=5).pack(side="left", padx=6)
    ttk.Label(mdur, text="(mais tempo = mais chance de acertar com voz por cima)",
              style="Muted.TLabel").pack(side="left", padx=6)

    m_titulo = tk.StringVar(value="")
    m_info = tk.StringVar(value="")
    m_url = {"v": ""}
    ttk.Label(t4, textvariable=m_titulo, font=("Segoe UI", 15, "bold"), wraplength=680).pack(anchor="w", pady=(4, 0))
    ttk.Label(t4, textvariable=m_info, style="Muted.TLabel", wraplength=680).pack(anchor="w")

    def mostrar_resultado(r):
        def _do():
            if not r:
                m_titulo.set("Não consegui identificar")
                m_info.set("Tente de novo com mais tempo de escuta, volume mais alto ou menos fala por cima.")
                m_url["v"] = ""
            else:
                m_titulo.set(f"{r['artista']} - {r['titulo']}")
                conf = r["votos"] / max(r["total"], 1)
                nivel = "alta" if conf >= 0.5 else ("média" if r["votos"] >= 2 else "baixa")
                m_info.set(f"Confiança {nivel}: {r['votos']} de {r['total']} trechos concordaram."
                           + ("  Outras possibilidades: " + "; ".join(f"{a} - {t}" for a, t, _ in r["outros"][:2])
                              if r["outros"] else ""))
                m_url["v"] = r["url"]
            b_open.configure(state="normal" if m_url["v"] else "disabled")
        root.after(0, _do)

    def go4():
        fonte = m_src.get()
        if fonte == "arquivo" and not Path(m_file.get().strip()).exists():
            return messagebox.showwarning(APP_NAME, "Escolha um arquivo válido.")
        try:
            seg = max(5, min(int(m_dur.get()), 60))
        except ValueError:
            return messagebox.showwarning(APP_NAME, "O tempo de escuta precisa ser um número.")
        m_titulo.set("")
        m_info.set("")
        b_open.configure(state="disabled")
        worker(identificar_musica, fonte, m_file.get().strip(), seg, log, progress, mostrar_resultado)

    b4row = ttk.Frame(t4)
    b4row.pack(anchor="w", pady=(6, 0))
    b4 = ttk.Button(b4row, text="Ouvir e identificar", style="Accent.TButton", command=go4)
    b4.pack(side="left")
    buttons.append(b4)
    b_open = ttk.Button(b4row, text="Abrir no Shazam", state="disabled",
                        command=lambda: m_url["v"] and webbrowser.open(m_url["v"]))
    b_open.pack(side="left", padx=(10, 0))

    log("Bem-vindo ao Dex's Utilities. Escolha uma aba para começar.")

    # ---- splash ----
    sp = tk.Toplevel(root)
    sp.overrideredirect(True)
    sp.configure(bg=BG)
    w, h = 460, 340
    sp.geometry(f"{w}x{h}+{(sp.winfo_screenwidth() - w) // 2}+{(sp.winfo_screenheight() - h) // 2}")
    sp.attributes("-alpha", 0.0)
    sp.attributes("-topmost", True)
    frame = tk.Frame(sp, bg=BG, highlightbackground=ACCENT, highlightthickness=2)
    frame.pack(fill="both", expand=True)
    tk.Label(frame, image=logo_big, bg=BG).pack(pady=(32, 10))
    tk.Label(frame, text=APP_NAME, bg=BG, fg=FG, font=("Segoe UI", 24, "bold")).pack()
    tk.Label(frame, text="carregando...", bg=BG, fg=MUTED, font=("Segoe UI", 10)).pack(pady=(4, 14))
    canvas = tk.Canvas(frame, width=300, height=4, bg=CARD, highlightthickness=0)
    canvas.pack()
    fill = canvas.create_rectangle(0, 0, 0, 4, fill=ACCENT, width=0)

    steps = {"n": 0}
    total = 50  # 50 * 40ms = 2s

    def tick():
        n = steps["n"] = steps["n"] + 1
        canvas.coords(fill, 0, 0, 300 * min(n / total, 1), 4)
        if n <= 12:
            sp.attributes("-alpha", n / 12)
        if n >= total - 10:
            sp.attributes("-alpha", max((total - n) / 10, 0))
        if n >= total:
            sp.destroy()
            root.deiconify()
            return
        sp.after(40, tick)

    tick()
    root.mainloop()


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--gallery-dl":
        _gallery_dl_main()
    else:
        run_gui()
