#!/usr/bin/env python3
"""Generate the browsable image and animation gallery."""

from __future__ import annotations

import hashlib
import html
import json
import os
import shutil
import subprocess
import sys
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote


IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".avif", ".svg", ".bmp", ".tiff", ".tif"}
VIDEO_EXTS = {".mp4"}
SKIP_DIRS = {".git", ".github", ".generated", "scripts", "node_modules", ".DS_Store"}
SKIP_FILES = {".DS_Store", "screenshot.jpg"}
PREVIEW_DURATION_SECONDS = 1


@dataclass(frozen=True)
class Media:
    path: str
    kind: str
    preview: str | None = None
    frame_rate: float | None = None


def is_animated_webp(path: Path) -> bool:
    """Return whether a WebP container includes animation data."""
    with path.open("rb") as source:
        return b"ANIM" in source.read(4096)


def media_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()[:12]


def probe_frame_rate(path: Path) -> float | None:
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        return None

    result = subprocess.run(
        [
            ffprobe,
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=avg_frame_rate",
            "-of",
            "json",
            str(path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    rate = json.loads(result.stdout)["streams"][0].get("avg_frame_rate", "0/0")
    numerator, denominator = (int(part) for part in rate.split("/", 1))
    return numerator / denominator if denominator else None


def generate_preview(source: Path, preview: Path) -> None:
    if preview.exists():
        return

    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError(
            f"ffmpeg is required to generate the preview for {source.relative_to(source.parents[1])}"
        )

    preview.parent.mkdir(parents=True, exist_ok=True)
    temporary = preview.with_suffix(".tmp.gif")
    subprocess.run(
        [
            ffmpeg,
            "-v",
            "error",
            "-y",
            "-i",
            str(source),
            "-t",
            str(PREVIEW_DURATION_SECONDS),
            "-filter_complex",
            (
                "fps=10,scale=480:-1:flags=lanczos,split[frames][palette_source];"
                "[palette_source]palettegen=max_colors=96[palette];"
                "[frames][palette]paletteuse=dither=sierra2_4a"
            ),
            "-loop",
            "0",
            str(temporary),
        ],
        check=True,
    )
    temporary.replace(preview)


def collect_media(root: Path) -> dict[str, list[Media]]:
    """Collect images and animations, grouped by their relative folder."""
    folders: dict[str, list[Media]] = defaultdict(list)

    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in sorted(dirnames) if d not in SKIP_DIRS and not d.startswith(".")]
        rel_dir = Path(dirpath).relative_to(root)
        folder_key = rel_dir.as_posix()

        for filename in sorted(filenames):
            if filename in SKIP_FILES:
                continue

            source = Path(dirpath) / filename
            suffix = source.suffix.lower()
            is_video = suffix in VIDEO_EXTS
            is_animated_image = suffix == ".webp" and is_animated_webp(source)
            if not is_video and suffix not in IMAGE_EXTS:
                continue

            relative_path = (rel_dir / filename).as_posix()
            if is_video or is_animated_image:
                preview_name = f"{source.stem}-{media_digest(source)}.gif"
                preview = root / ".generated" / "previews" / preview_name
                generate_preview(source, preview)
                folders[folder_key].append(
                    Media(
                        path=relative_path,
                        kind="video" if is_video else "animated-webp",
                        preview=preview.relative_to(root).as_posix(),
                        frame_rate=probe_frame_rate(source) if is_video else None,
                    )
                )
            else:
                folders[folder_key].append(Media(path=relative_path, kind="image"))

    result: dict[str, list[Media]] = {}
    if "." in folders:
        result["."] = folders.pop(".")
    for key in sorted(folders):
        result[key] = folders[key]
    return result


def folder_title(key: str) -> str:
    if key == ".":
        return "Root"
    return key.replace("/", " / ").replace("_", " ").strip()


def url(path: str) -> str:
    return quote(path, safe="/.")


def build_html(folders: dict[str, list[Media]], repo_name: str = "Inspirations") -> str:
    sections_html = []
    nav_thumbs = []

    for folder_key, media_items in folders.items():
        if not media_items:
            continue
        anchor = folder_key.replace("/", "-").replace(".", "root")
        title = folder_title(folder_key)
        cover = media_items[0].preview or media_items[0].path
        nav_thumbs.append(
            f'    <li>\n'
            f'      <a class="nav-thumb" href="#{html.escape(anchor)}">\n'
            f'        <img src="{url(cover)}" alt="{html.escape(title)}" loading="lazy">\n'
            f'        <span>{html.escape(title)}</span>\n'
            f'      </a>\n'
            f'    </li>'
        )
    nav_html = "\n".join(nav_thumbs)

    for folder_key, media_items in folders.items():
        if not media_items:
            continue

        title = folder_title(folder_key)
        anchor = folder_key.replace("/", "-").replace(".", "root")
        cards = []
        for media in media_items:
            filename = Path(media.path).name
            escaped_filename = html.escape(filename)
            if media.kind == "image":
                cards.append(
                    f'        <a class="card" href="{url(media.path)}" target="_blank" rel="noopener">\n'
                    f'          <img src="{url(media.path)}" alt="{escaped_filename}" '
                    f'title="{escaped_filename}" loading="lazy">\n'
                    f'        </a>'
                )
                continue

            frame_rate = f' data-fps="{media.frame_rate:.6g}"' if media.frame_rate else ""
            cards.append(
                f'        <button class="card media-card" type="button" data-kind="{media.kind}" '
                f'data-src="{url(media.path)}" data-title="{escaped_filename}"{frame_rate}>\n'
                f'          <img src="{url(media.preview or media.path)}" alt="{escaped_filename}" '
                f'title="Open {escaped_filename}" loading="lazy">\n'
                f'          <span class="media-badge" aria-hidden="true">&#9654;</span>\n'
                f'        </button>'
            )

        count = len(media_items)
        section = (
            f'  <section id="{html.escape(anchor)}">\n'
            f'    <details open>\n'
            f'      <summary>\n'
            f'        <span class="folder-title">{html.escape(title)}</span>\n'
            f'        <span class="count">{count} item{"s" if count != 1 else ""}</span>\n'
            f'        <a class="top-btn" href="#top" title="Back to top">↑ top</a>\n'
            f'      </summary>\n'
            f'      <div class="masonry">\n'
            + "\n".join(cards)
            + "\n"
            f'      </div>\n'
            f'    </details>\n'
            f'  </section>'
        )
        sections_html.append(section)

    total_items = sum(len(items) for items in folders.values())
    total_animations = sum(
        media.kind != "image" for items in folders.values() for media in items
    )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{html.escape(repo_name)}</title>
  <style>
    *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
    :root {{
      --bg: #111; --surface: #1a1a1a; --border: #2a2a2a; --accent: #c8a96e;
      --text: #e0e0e0; --muted: #777; --radius: 6px; --thumb: 120px;
    }}
    body {{
      background: var(--bg); color: var(--text);
      font-family: system-ui, -apple-system, sans-serif; line-height: 1.5;
    }}
    button {{ color: inherit; font: inherit; }}
    header {{ padding: 2rem 2rem 1.2rem; border-bottom: 1px solid var(--border); }}
    header h1 {{ font-size: 1.8rem; font-weight: 700; letter-spacing: -.02em; }}
    header .meta {{ color: var(--muted); font-size: .875rem; margin-top: .2rem; }}
    nav {{ padding: 1.25rem 2rem; border-bottom: 1px solid var(--border); background: var(--surface); }}
    nav ul {{ list-style: none; display: flex; flex-wrap: wrap; gap: 10px; }}
    .nav-thumb {{
      display: block; position: relative; width: var(--thumb); height: var(--thumb);
      border-radius: var(--radius); overflow: hidden; border: 1px solid var(--border);
      text-decoration: none; transition: border-color .15s, transform .15s;
    }}
    .nav-thumb:hover {{ border-color: var(--accent); transform: translateY(-2px); }}
    .nav-thumb img {{ width: 100%; height: 100%; object-fit: cover; display: block; }}
    .nav-thumb span {{
      position: absolute; inset: auto 0 0 0; padding: .3rem .4rem;
      background: linear-gradient(transparent, rgba(0,0,0,.75)); color: #fff;
      font-size: .65rem; font-weight: 600; line-height: 1.2; text-align: center;
      word-break: break-word;
    }}
    main {{ padding: 2rem; max-width: 1600px; margin: 0 auto; }}
    section {{ margin-bottom: 2rem; }}
    details > summary {{
      list-style: none; display: flex; align-items: center; gap: .75rem; cursor: pointer;
      padding: .6rem .8rem; background: var(--surface); border: 1px solid var(--border);
      border-radius: var(--radius); margin-bottom: .75rem; user-select: none;
    }}
    details > summary::-webkit-details-marker {{ display: none; }}
    details > summary::before {{
      content: "▶"; font-size: .65rem; color: var(--muted); transition: transform .2s;
      flex-shrink: 0;
    }}
    details[open] > summary::before {{ transform: rotate(90deg); }}
    details > summary:hover {{ border-color: var(--accent); }}
    .folder-title {{ font-size: 1rem; font-weight: 600; letter-spacing: -.01em; }}
    .count {{ font-size: .75rem; color: var(--muted); margin-left: auto; }}
    .top-btn {{
      display: inline-flex; font-size: .72rem; font-weight: 500; color: var(--accent);
      text-decoration: none; padding: .15rem .45rem; border: 1px solid var(--border);
      border-radius: calc(var(--radius) - 1px); flex-shrink: 0; margin-left: .5rem;
    }}
    .top-btn:hover {{ border-color: var(--accent); background: rgba(200,169,110,.08); }}
    .masonry {{ columns: 3; column-gap: 8px; }}
    .card {{
      display: block; position: relative; width: 100%; break-inside: avoid; margin-bottom: 8px;
      padding: 0; border-radius: var(--radius); overflow: hidden; border: 1px solid var(--border);
      background: #000; transition: border-color .15s, opacity .15s;
    }}
    .card:hover {{ border-color: var(--accent); opacity: .9; }}
    .card img {{ width: 100%; height: auto; display: block; }}
    .media-card {{ cursor: pointer; text-align: left; }}
    .media-badge {{
      position: absolute; left: 50%; top: 50%; translate: -50% -50%;
      display: grid; place-items: center; width: 3rem; height: 3rem; padding-left: .2rem;
      border-radius: 50%; background: rgba(0,0,0,.72); border: 1px solid rgba(255,255,255,.55);
      color: #fff; font-size: 1.15rem; pointer-events: none;
    }}
    .player {{
      width: min(94vw, 1100px); max-height: 94vh; padding: 0; overflow: hidden;
      border: 1px solid var(--border); border-radius: 10px; background: var(--surface); color: var(--text);
    }}
    .player::backdrop {{ background: rgba(0,0,0,.82); backdrop-filter: blur(3px); }}
    .player-header, .player-controls {{
      display: flex; align-items: center; gap: .65rem; padding: .7rem .85rem;
    }}
    .player-header {{ border-bottom: 1px solid var(--border); }}
    .player-title {{ overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }}
    .player-close {{ margin-left: auto; }}
    .player-stage {{
      display: grid; place-items: center; height: min(72vh, 760px); background: #050505;
    }}
    .player-stage video, .player-stage canvas {{
      display: block; max-width: 100%; max-height: 100%; object-fit: contain;
    }}
    .player-controls {{ justify-content: center; border-top: 1px solid var(--border); }}
    .player-controls button, .player-close {{
      min-width: 2.5rem; padding: .4rem .7rem; border-radius: 5px;
      border: 1px solid var(--border); background: #222; cursor: pointer;
    }}
    .player-controls button:hover, .player-close:hover {{ border-color: var(--accent); }}
    .frame-status {{ min-width: 9rem; text-align: center; color: var(--muted); font-variant-numeric: tabular-nums; }}
    .player-error {{ color: #ff9b9b; padding: 1rem; }}
    @media (max-width: 900px) {{ .masonry {{ columns: 2; }} }}
    @media (max-width: 520px) {{
      .masonry {{ columns: 1; }} .nav-thumb {{ --thumb: 90px; }}
      main, nav {{ padding-left: 1rem; padding-right: 1rem; }}
    }}
    .fab-cluster {{
      position: fixed; bottom: .75rem; right: .75rem; display: flex;
      flex-direction: column; gap: .45rem; z-index: 100;
    }}
    .fab {{
      display: flex; align-items: center; justify-content: center; width: 2.4rem; height: 2.4rem;
      border-radius: 50%; border: 1px solid var(--border); background: var(--surface);
      color: var(--muted); font-size: 1rem; cursor: pointer; text-decoration: none;
      box-shadow: 0 2px 8px rgba(0,0,0,.4);
    }}
    .fab:hover {{ border-color: var(--accent); color: var(--accent); }}
  </style>
</head>
<body>
  <header id="top">
    <h1>{html.escape(repo_name)}</h1>
    <p class="meta">{total_items} items &middot; {total_animations} animation{"s" if total_animations != 1 else ""} &middot; {len(folders)} folder{"s" if len(folders) != 1 else ""}</p>
  </header>
  <nav><ul>
{nav_html}
  </ul></nav>
  <main>
{"".join(chr(10) + section for section in sections_html)}
  </main>

  <dialog class="player" id="player" aria-labelledby="player-title">
    <div class="player-header">
      <strong class="player-title" id="player-title"></strong>
      <button class="player-close" type="button" aria-label="Close player">&times;</button>
    </div>
    <div class="player-stage" id="player-stage"></div>
    <div class="player-controls">
      <button type="button" id="previous-frame" title="Previous frame">&#9664; Frame</button>
      <button type="button" id="toggle-play" title="Play or pause">&#9654;</button>
      <button type="button" id="next-frame" title="Next frame">Frame &#9654;</button>
      <span class="frame-status" id="frame-status">Frame 1</span>
    </div>
  </dialog>

  <div class="fab-cluster">
    <a class="fab" href="#top" title="Back to top">&#9651;</a>
    <button class="fab" id="fab-section" title="Current section" onclick="fabSection()">&#9650;</button>
  </div>

  <script>
    var player = document.getElementById('player');
    var stage = document.getElementById('player-stage');
    var frameStatus = document.getElementById('frame-status');
    var toggle = document.getElementById('toggle-play');
    var activeMedia = null;

    function fabSection() {{
      var sections = Array.from(document.querySelectorAll('section'));
      var current = null;
      for (var i = 0; i < sections.length; i++) {{
        if (sections[i].getBoundingClientRect().top <= 80) current = sections[i];
        else break;
      }}
      var target = current || sections[0];
      if (target) (target.querySelector('summary') || target).scrollIntoView({{ behavior: 'smooth', block: 'start' }});
    }}

    function updateVideoStatus() {{
      if (!activeMedia || activeMedia.kind !== 'video') return;
      var frame = Math.floor(activeMedia.element.currentTime * activeMedia.fps + 0.5) + 1;
      var total = activeMedia.element.duration
        ? Math.max(1, Math.floor(activeMedia.element.duration * activeMedia.fps))
        : null;
      frameStatus.textContent = total ? 'Frame ' + frame + ' / ' + total : 'Frame ' + frame;
      toggle.innerHTML = activeMedia.element.paused ? '&#9654;' : '&#10074;&#10074;';
    }}

    async function showWebpFrame(index) {{
      if (!activeMedia || activeMedia.kind !== 'animated-webp') return;
      var frameCount = activeMedia.track.frameCount;
      activeMedia.index = (index + frameCount) % frameCount;
      var result = await activeMedia.decoder.decode({{ frameIndex: activeMedia.index }});
      var frame = result.image;
      var canvas = activeMedia.element;
      canvas.width = frame.displayWidth;
      canvas.height = frame.displayHeight;
      canvas.getContext('2d').drawImage(frame, 0, 0);
      activeMedia.duration = Math.max(16, frame.duration / 1000 || 100);
      frame.close();
      frameStatus.textContent = 'Frame ' + (activeMedia.index + 1) + ' / ' + frameCount;
    }}

    function stopPlayback() {{
      if (!activeMedia) return;
      if (activeMedia.kind === 'video') activeMedia.element.pause();
      if (activeMedia.timer) clearTimeout(activeMedia.timer);
      activeMedia.timer = null;
      toggle.innerHTML = '&#9654;';
    }}

    async function playNextWebpFrame() {{
      if (!activeMedia || activeMedia.kind !== 'animated-webp' || !activeMedia.timer) return;
      await showWebpFrame(activeMedia.index + 1);
      activeMedia.timer = setTimeout(playNextWebpFrame, activeMedia.duration);
    }}

    async function openMedia(card) {{
      stage.replaceChildren();
      frameStatus.textContent = 'Loading...';
      document.getElementById('player-title').textContent = card.dataset.title;
      player.showModal();

      if (card.dataset.kind === 'video') {{
        var video = document.createElement('video');
        video.src = card.dataset.src;
        video.preload = 'metadata';
        video.playsInline = true;
        video.addEventListener('timeupdate', updateVideoStatus);
        video.addEventListener('seeked', updateVideoStatus);
        video.addEventListener('play', updateVideoStatus);
        video.addEventListener('pause', updateVideoStatus);
        activeMedia = {{
          kind: 'video',
          element: video,
          fps: Number(card.dataset.fps) || 30
        }};
        stage.appendChild(video);
        video.addEventListener('loadedmetadata', updateVideoStatus, {{ once: true }});
        return;
      }}

      if (!('ImageDecoder' in window)) {{
        stage.innerHTML = '<p class="player-error">Frame-by-frame animated WebP playback is not supported by this browser.</p>';
        frameStatus.textContent = 'Unavailable';
        return;
      }}

      try {{
        var response = await fetch(card.dataset.src);
        var decoder = new ImageDecoder({{ data: await response.arrayBuffer(), type: 'image/webp' }});
        await decoder.tracks.ready;
        var canvas = document.createElement('canvas');
        activeMedia = {{
          kind: 'animated-webp',
          element: canvas,
          decoder: decoder,
          track: decoder.tracks.selectedTrack,
          index: 0,
          timer: null,
          duration: 100
        }};
        stage.appendChild(canvas);
        await showWebpFrame(0);
      }} catch (error) {{
        stage.innerHTML = '<p class="player-error">Unable to decode this animated WebP.</p>';
        frameStatus.textContent = 'Unavailable';
        console.error(error);
      }}
    }}

    function stepFrame(direction) {{
      if (!activeMedia) return;
      stopPlayback();
      if (activeMedia.kind === 'video') {{
        var nextFrame = Math.round(activeMedia.element.currentTime * activeMedia.fps) + direction;
        var maxFrame = activeMedia.element.duration
          ? Math.max(0, Math.floor(activeMedia.element.duration * activeMedia.fps) - 1)
          : Number.MAX_SAFE_INTEGER;
        activeMedia.element.currentTime = Math.min(maxFrame, Math.max(0, nextFrame)) / activeMedia.fps;
      }} else {{
        showWebpFrame(activeMedia.index + direction);
      }}
    }}

    document.querySelectorAll('.media-card').forEach(function(card) {{
      card.addEventListener('click', function() {{ openMedia(card); }});
    }});
    document.getElementById('previous-frame').addEventListener('click', function() {{ stepFrame(-1); }});
    document.getElementById('next-frame').addEventListener('click', function() {{ stepFrame(1); }});
    toggle.addEventListener('click', function() {{
      if (!activeMedia) return;
      if (activeMedia.kind === 'video') {{
        if (activeMedia.element.paused) activeMedia.element.play();
        else activeMedia.element.pause();
      }} else if (activeMedia.timer) {{
        stopPlayback();
      }} else {{
        activeMedia.timer = setTimeout(playNextWebpFrame, 0);
        toggle.innerHTML = '&#10074;&#10074;';
      }}
    }});
    document.querySelector('.player-close').addEventListener('click', function() {{ player.close(); }});
    player.addEventListener('click', function(event) {{ if (event.target === player) player.close(); }});
    player.addEventListener('close', function() {{
      stopPlayback();
      if (activeMedia && activeMedia.decoder) activeMedia.decoder.close();
      activeMedia = null;
      stage.replaceChildren();
    }});
    document.addEventListener('keydown', function(event) {{
      if (!player.open) return;
      if (event.key === 'ArrowLeft') stepFrame(-1);
      if (event.key === 'ArrowRight') stepFrame(1);
      if (event.key === ' ') {{ event.preventDefault(); toggle.click(); }}
    }});
  </script>
</body>
</html>
"""


def main() -> None:
    repo_root = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else Path(__file__).parent.parent.resolve()
    try:
        folders = collect_media(repo_root)
    except (OSError, subprocess.CalledProcessError, RuntimeError, ValueError, KeyError) as error:
        print(f"Unable to generate gallery: {error}", file=sys.stderr)
        sys.exit(1)

    if not any(folders.values()):
        print("No supported media found.", file=sys.stderr)
        sys.exit(1)

    output = repo_root / "index.html"
    output.write_text(build_html(folders, repo_root.name), encoding="utf-8")
    item_count = sum(len(items) for items in folders.values())
    print(f"Generated {output} ({item_count} items, {len(folders)} folders)")


if __name__ == "__main__":
    main()
