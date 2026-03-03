#!/usr/bin/env python3
"""
Generate index.html listing all images in the repository, grouped by folder,
displayed in a responsive 3-column grid that preserves each image's aspect ratio.
"""

import os
import sys
from pathlib import Path
from collections import defaultdict

# Supported image extensions
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".avif", ".svg", ".bmp", ".tiff", ".tif"}

# Folders / files to skip
SKIP_DIRS = {".git", ".github", "scripts", "node_modules", ".DS_Store"}
SKIP_FILES = {".DS_Store"}


def collect_images(root: Path) -> dict[str, list[str]]:
    """
    Walk the repo and return a dict mapping folder display name → list of
    relative-to-root image paths (using forward slashes, URL-safe).
    The root folder itself is stored under the key '.'.
    """
    folders: dict[str, list[str]] = defaultdict(list)

    for dirpath, dirnames, filenames in os.walk(root):
        # Prune ignored directories in-place so os.walk skips them
        dirnames[:] = [d for d in sorted(dirnames) if d not in SKIP_DIRS and not d.startswith(".")]

        rel_dir = Path(dirpath).relative_to(root)
        folder_key = str(rel_dir).replace(os.sep, "/")  # '.' for root

        images = sorted(
            f for f in filenames
            if Path(f).suffix.lower() in IMAGE_EXTS and f not in SKIP_FILES
        )
        for img in images:
            rel_path = (rel_dir / img).as_posix()
            folders[folder_key].append(rel_path)

    # Return only folders that actually contain images, root first then sorted
    result: dict[str, list[str]] = {}
    if "." in folders:
        result["."] = folders.pop(".")
    for key in sorted(folders.keys()):
        result[key] = folders[key]
    return result


def folder_title(key: str) -> str:
    """Human-readable title from folder key."""
    if key == ".":
        return "Root"
    # Replace slashes and underscores, title-case
    return key.replace("/", " / ").replace("_", " ").strip()


def build_html(folders: dict[str, list[str]], repo_name: str = "Inspirations") -> str:
    sections_html = []

    # Build nav thumbnails (one per folder, first image as cover)
    nav_thumbs = []
    for folder_key, images in folders.items():
        if not images:
            continue
        anchor = folder_key.replace("/", "-").replace(".", "root")
        title = folder_title(folder_key)
        cover_url = images[0].replace(" ", "%20")
        nav_thumbs.append(
            f'    <li>\n'
            f'      <a class="nav-thumb" href="#{anchor}">\n'
            f'        <img src="{cover_url}" alt="{title}" loading="lazy">\n'
            f'        <span>{title}</span>\n'
            f'      </a>\n'
            f'    </li>'
        )
    nav_html = "\n".join(nav_thumbs)

    for folder_key, images in folders.items():
        if not images:
            continue

        title = folder_title(folder_key)
        anchor = folder_key.replace("/", "-").replace(".", "root")
        cards = []
        for rel_path in images:
            filename = Path(rel_path).name
            url_path = rel_path.replace(" ", "%20")
            card = (
                f'        <a class="card" href="{url_path}" target="_blank" rel="noopener">\n'
                f'          <img src="{url_path}" alt="{filename}" title="{filename}" loading="lazy">\n'
                f'        </a>'
            )
            cards.append(card)

        section = (
            f'  <section id="{anchor}">\n'
            f'    <details open>\n'
            f'      <summary>\n'
            f'        <span class="folder-title">{title}</span>\n'
            f'        <span class="count">{len(images)} image{"s" if len(images) != 1 else ""}</span>\n'
            f'        <a class="top-btn" href="#top" title="Back to top">↑ top</a>\n'
            f'      </summary>\n'
            f'      <div class="masonry">\n'
            + "\n".join(cards) + "\n"
            f'      </div>\n'
            f'    </details>\n'
            f'  </section>'
        )
        sections_html.append(section)

    total_images = sum(len(v) for v in folders.values())

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{repo_name}</title>
  <style>
    *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}

    :root {{
      --bg: #111;
      --surface: #1a1a1a;
      --border: #2a2a2a;
      --accent: #c8a96e;
      --text: #e0e0e0;
      --muted: #666;
      --radius: 6px;
      --thumb: 120px;
    }}

    body {{
      background: var(--bg);
      color: var(--text);
      font-family: system-ui, -apple-system, sans-serif;
      line-height: 1.5;
    }}

    /* ── Header ── */
    header {{
      padding: 2rem 2rem 1.2rem;
      border-bottom: 1px solid var(--border);
    }}
    header h1 {{ font-size: 1.8rem; font-weight: 700; letter-spacing: -.02em; }}
    header .meta {{ color: var(--muted); font-size: .875rem; margin-top: .2rem; }}

    /* ── Nav: thumbnail grid ── */
    nav {{
      padding: 1.25rem 2rem;
      border-bottom: 1px solid var(--border);
      background: var(--surface);
    }}
    nav ul {{
      list-style: none;
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
    }}

    /* Square thumbnail card */
    .nav-thumb {{
      display: block;
      position: relative;
      width: var(--thumb);
      height: var(--thumb);
      border-radius: var(--radius);
      overflow: hidden;
      border: 1px solid var(--border);
      text-decoration: none;
      transition: border-color .15s, transform .15s;
    }}
    .nav-thumb:hover {{
      border-color: var(--accent);
      transform: translateY(-2px);
    }}
    .nav-thumb img {{
      width: 100%;
      height: 100%;
      object-fit: cover;
      display: block;
    }}
    /* Folder name overlay */
    .nav-thumb span {{
      position: absolute;
      inset: auto 0 0 0;
      padding: .3rem .4rem;
      background: linear-gradient(transparent, rgba(0,0,0,.75));
      color: #fff;
      font-size: .65rem;
      font-weight: 600;
      line-height: 1.2;
      letter-spacing: .01em;
      text-align: center;
      word-break: break-word;
    }}

    /* ── Main layout ── */
    main {{ padding: 2rem; max-width: 1600px; margin: 0 auto; }}

    section {{ margin-bottom: 2rem; }}

    /* ── Collapsible section header ── */
    details > summary {{
      list-style: none;
      display: flex;
      align-items: center;
      gap: .75rem;
      cursor: pointer;
      padding: .6rem .8rem;
      background: var(--surface);
      border: 1px solid var(--border);
      border-radius: var(--radius);
      margin-bottom: .75rem;
      user-select: none;
    }}
    details > summary::-webkit-details-marker {{ display: none; }}
    details > summary::before {{
      content: "▶";
      font-size: .65rem;
      color: var(--muted);
      transition: transform .2s;
      flex-shrink: 0;
    }}
    details[open] > summary::before {{ transform: rotate(90deg); }}
    details > summary:hover {{ border-color: var(--accent); }}

    .folder-title {{
      font-size: 1rem;
      font-weight: 600;
      letter-spacing: -.01em;
    }}
    .count {{
      font-size: .75rem;
      font-weight: 400;
      color: var(--muted);
      margin-left: auto;
    }}

    /* Back-to-top button inside summary */
    .top-btn {{
      display: inline-flex;
      align-items: center;
      gap: .25rem;
      font-size: .72rem;
      font-weight: 500;
      color: var(--accent);
      text-decoration: none;
      padding: .15rem .45rem;
      border: 1px solid var(--border);
      border-radius: calc(var(--radius) - 1px);
      transition: border-color .15s, background .15s;
      flex-shrink: 0;
      margin-left: .5rem;
    }}
    .top-btn:hover {{
      border-color: var(--accent);
      background: rgba(200,169,110,.08);
    }}

    /* ── Masonry ── */
    .masonry {{
      columns: 3;
      column-gap: 8px;
    }}

    /* ── Card ── */
    .card {{
      display: block;
      break-inside: avoid;
      margin-bottom: 8px;
      border-radius: var(--radius);
      overflow: hidden;
      border: 1px solid var(--border);
      transition: border-color .15s, opacity .15s;
    }}
    .card:hover {{ border-color: var(--accent); opacity: .9; }}
    .card img {{
      width: 100%;
      height: auto;
      display: block;
    }}

    /* ── Responsive ── */
    @media (max-width: 900px)  {{ .masonry {{ columns: 2; }} }}
    @media (max-width: 520px)  {{ .masonry {{ columns: 1; }} .nav-thumb {{ --thumb: 90px; }} }}
  </style>
</head>
<body>
  <header id="top">
    <h1>{repo_name}</h1>
    <p class="meta">{total_images} images &middot; {len(folders)} folder{"s" if len(folders) != 1 else ""}</p>
  </header>
  <nav>
    <ul>
{nav_html}
    </ul>
  </nav>
  <main>
{"".join(chr(10) + s for s in sections_html)}
  </main>
</body>
</html>
"""
    return html


def main() -> None:
    # Accept optional repo root argument; default to parent of this script
    if len(sys.argv) > 1:
        repo_root = Path(sys.argv[1]).resolve()
    else:
        repo_root = Path(__file__).parent.parent.resolve()

    repo_name = repo_root.name
    folders = collect_images(repo_root)

    if not any(folders.values()):
        print("No images found.", file=sys.stderr)
        sys.exit(1)

    html = build_html(folders, repo_name)

    out_path = repo_root / "index.html"
    out_path.write_text(html, encoding="utf-8")
    print(f"Generated {out_path}  ({sum(len(v) for v in folders.values())} images, {len(folders)} folders)")


if __name__ == "__main__":
    main()
