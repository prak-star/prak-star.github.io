#!/usr/bin/env python3
"""
Regenerates the machine-readable representations of index.html:

  1. data/resume.json     - full resume in JSON Resume schema
                             (https://jsonresume.org/schema/), used by
                             AI agents / crawlers that want the whole
                             work history, education, skills, etc.
  2. index.html            - a <script type="application/ld+json"> block
                             in <head> is inserted/updated in place with
                             a schema.org Person summary, for search
                             engines (Google rich results, etc).

Re-run this any time index.html content changes:

    python3 scripts/generate_resume_json.py

The parser is intentionally tied to the current structure of index.html
(company link -> position paragraph -> highlights list, per section id).
If you restructure a section in the HTML, update the matching extractor
function below.
"""

import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from html_to_json import TreeBuilder  # noqa: E402

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INDEX_HTML = os.path.join(ROOT_DIR, "index.html")
RESUME_JSON = os.path.join(ROOT_DIR, "data", "resume.json")

SITE_URL = "https://prak-star.github.io/"
LINKEDIN_URL = "https://www.linkedin.com/in/prakriti-sharma-sapkota/"
GITHUB_URL = "https://github.com/prak-star"
EMAIL = "prakritiuvic@gmail.com"


# ---------------------------------------------------------------- helpers

def parse_layout_tree(html_path):
    with open(html_path, "r", encoding="utf-8") as f:
        html = f.read()
    builder = TreeBuilder()
    builder.feed(html)
    return builder.root


def get_text(node):
    """Concatenate all #text descendants, collapsing whitespace."""
    parts = []

    def walk(n):
        if n.get("tag") == "#text":
            parts.append(n["text"])
        for c in n.get("children", []):
            walk(c)

    walk(node)
    return re.sub(r"\s+", " ", " ".join(parts)).strip()


def find_tag(node, tag):
    """First direct child with this tag."""
    for c in node.get("children", []):
        if c.get("tag") == tag:
            return c
    return None


def find_all_tags(node, tag):
    return [c for c in node.get("children", []) if c.get("tag") == tag]


def find_anchor(node):
    """First <a> anywhere under node -> (text, href)."""
    if node.get("tag") == "a":
        return get_text(node), node["attrs"].get("href")
    for c in node.get("children", []):
        text, href = find_anchor(c)
        if href:
            return text, href
    return None, None


def split_keywords(text):
    """Split on top-level commas only, ignoring commas inside parentheses."""
    parts, buf, depth = [], "", 0
    for ch in text:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth = max(0, depth - 1)
        if ch == "," and depth == 0:
            parts.append(buf)
            buf = ""
        else:
            buf += ch
    if buf:
        parts.append(buf)
    return [p.strip() for p in parts if p.strip()]


def sectionize(root):
    """
    Split #layout-content's direct children into sections keyed by the
    id= of the <a> inside each <h2>. Everything between one h2 and the
    next belongs to that section (preserving order).
    """
    sections = {}
    current = None
    for child in root.get("children", []):
        if child.get("tag") == "h2":
            a = find_tag(child, "a")
            sec_id = a["attrs"].get("id") if a else None
            current = (sec_id or "").lower()
            sections.setdefault(current, [])
            continue
        if current is not None:
            sections[current].append(child)
    return sections


def highlights_from_ul(ul_node):
    """
    Flatten a highlights <ul>. A leaf <li> is a highlight string. A <li>
    with a bold category label and a nested <ul> becomes
    "Category: item" for each nested item.
    """
    out = []
    if not ul_node:
        return out
    for li in find_all_tags(ul_node, "li"):
        nested_ul = find_tag(li, "ul")
        bold = find_tag(li, "b")
        if nested_ul and bold:
            category = get_text(bold).rstrip(":")
            for sub_li in find_all_tags(nested_ul, "li"):
                out.append(f"{category}: {get_text(sub_li)}")
        else:
            out.append(get_text(li))
    return out


# ------------------------------------------------------------ extractors

def extract_basics(sections):
    return {
        "name": "Prakriti Sharma",
        "label": "Civil Engineer, MASc., EIT",
        "email": EMAIL,
        "url": SITE_URL,
        "location": {"city": "Vancouver", "region": "Canada"},
        "profiles": [
            {"network": "LinkedIn", "url": LINKEDIN_URL},
            {"network": "GitHub", "url": GITHUB_URL},
        ],
    }


def extract_education(sections):
    nodes = sections.get("education", [])
    education = []
    current = None
    for node in nodes:
        tag = node.get("tag")
        if tag == "h4":
            if current:
                education.append(current)
            current = {"institution": get_text(node), "highlights": []}
        elif tag == "p" and current is not None:
            bold = find_tag(node, "b")
            italic = find_tag(node, "i")
            label = get_text(bold) if bold else None
            date = get_text(italic) if italic else None
            text_link, href = find_anchor(node)
            if label and label.lower().startswith("thesis"):
                current["thesis"] = {"title": text_link, "url": href}
            elif label and label.lower() == "major":
                current["area"] = get_text(italic) if italic else None
            elif label:
                current["studyType"] = label
                if date:
                    current["endDate"] = date
    if current:
        education.append(current)
    return education


def extract_skills(sections):
    nodes = sections.get("skills", [])
    skills = []
    for ul in nodes:
        if ul.get("tag") != "ul":
            continue
        for li in find_all_tags(ul, "li"):
            bold = find_tag(li, "b")
            italic = find_tag(li, "i")
            if not bold:
                continue
            name = get_text(bold).rstrip(":")
            keywords_text = get_text(italic) if italic else ""
            skills.append({"name": name, "keywords": split_keywords(keywords_text)})
    return skills


def extract_work_block(ul_node):
    """One <ul> of alternating <li>(org) / <p>(role+dates+highlights)."""
    entries = []
    children = ul_node.get("children", [])
    pending_org = None
    pending_url = None
    for child in children:
        tag = child.get("tag")
        if tag == "li":
            pending_org, pending_url = find_anchor(child)
        elif tag == "p" and pending_org:
            # position text = first #text child, dates = first <i>
            position = ""
            for c in child.get("children", []):
                if c.get("tag") == "#text":
                    position = c["text"].strip().rstrip(",")
                    break
            italic = find_tag(child, "i")
            date_range = get_text(italic) if italic else ""
            start_date, end_date = "", ""
            if "-" in date_range:
                start_date, end_date = [p.strip() for p in date_range.split("-", 1)]
            highlights_ul = find_tag(child, "ul")
            entries.append({
                "name": pending_org,
                "url": pending_url,
                "position": position,
                "startDate": start_date,
                "endDate": end_date,
                "highlights": highlights_from_ul(highlights_ul),
            })
            pending_org, pending_url = None, None
    return entries


def extract_experiences(sections):
    nodes = sections.get("experiences", [])
    work, academic = [], []
    current_label = None
    for node in nodes:
        if node.get("tag") == "h4":
            current_label = get_text(node)
        elif node.get("tag") == "ul":
            entries = extract_work_block(node)
            if current_label and "academic" in current_label.lower():
                academic.extend(entries)
            else:
                work.extend(entries)
    return work, academic


def extract_courses(sections):
    nodes = sections.get("courses", [])
    taken, taught = [], []
    mode = None
    for node in nodes:
        if node.get("tag") == "h4":
            mode = "taken" if "taken" in get_text(node).lower() else "taught"
        elif node.get("tag") == "ul" and mode == "taken":
            for li in find_all_tags(node, "li"):
                bold = find_tag(li, "b")
                category = get_text(bold).rstrip(":") if bold else None
                full_text = get_text(li)
                items_text = full_text.split(":", 1)[-1].strip() if category else full_text
                taken.append({"category": category, "items": split_keywords(items_text)})
        elif node.get("tag") == "p" and mode == "taught":
            taught = [i.strip() for i in get_text(node).split(",") if i.strip()]
    return {"taken": taken, "taught": taught}


def extract_certificates(sections):
    nodes = sections.get("certifications", [])
    certs = []
    current = None
    for node in nodes:
        if node.get("tag") == "h4":
            if current:
                certs.append(current)
            current = {"name": get_text(node).rstrip(":"), "highlights": [], "url": None}
        elif node.get("tag") == "ul" and current is not None:
            for li in find_all_tags(node, "li"):
                text_link, href = find_anchor(li)
                if href:
                    current["url"] = href
                else:
                    current["highlights"].append(get_text(li))
    if current:
        certs.append(current)
    return certs


def extract_trainings(sections):
    nodes = sections.get("trainings", [])
    groups = []
    current = None
    for node in nodes:
        if node.get("tag") == "h4":
            if current:
                groups.append(current)
            current = {"role": get_text(node), "items": []}
        elif node.get("tag") == "ul" and current is not None:
            for li in find_all_tags(node, "li"):
                current["items"].append(get_text(li))
    if current:
        groups.append(current)
    return groups


def extract_projects(sections):
    nodes = sections.get("projects", [])
    projects = []
    for ul in nodes:
        if ul.get("tag") != "ul":
            continue
        for li in find_all_tags(ul, "li"):
            bold = find_tag(li, "b")
            name = get_text(bold).rstrip(":") if bold else None
            full_text = get_text(li)
            description = full_text.split(":", 1)[-1].strip() if name else full_text
            projects.append({"name": name, "description": description})
    return projects


# ---------------------------------------------------------------- build

def build_resume():
    root = parse_layout_tree(INDEX_HTML)
    sections = sectionize(root)

    work, academic_work = extract_experiences(sections)

    resume = {
        "$schema": "https://jsonresume.org/schema/",
        "basics": extract_basics(sections),
        "education": extract_education(sections),
        "skills": extract_skills(sections),
        "work": work,
        "volunteer": academic_work,  # academic experiences, closest standard slot
        "certificates": extract_certificates(sections),
        "projects": extract_projects(sections),
        "courses": extract_courses(sections),   # non-standard extension
        "trainings": extract_trainings(sections),  # non-standard extension
    }
    return resume


def build_jsonld(resume):
    basics = resume["basics"]
    current_job = resume["work"][0] if resume["work"] else {}
    all_keywords = sorted({kw for skill in resume["skills"] for kw in skill["keywords"]})

    return {
        "@context": "https://schema.org",
        "@type": "Person",
        "name": basics["name"],
        "jobTitle": current_job.get("position", basics["label"]),
        "url": basics["url"],
        "email": f"mailto:{basics['email']}",
        "sameAs": [p["url"] for p in basics["profiles"]],
        "address": {
            "@type": "PostalAddress",
            "addressLocality": basics["location"]["city"],
            "addressCountry": basics["location"]["region"],
        },
        "worksFor": {
            "@type": "Organization",
            "name": current_job["name"].split(",")[0].strip(),
        } if current_job.get("name") else None,
        "alumniOf": [
            {"@type": "EducationalOrganization", "name": e["institution"]}
            for e in resume["education"]
        ],
        "knowsAbout": all_keywords,
    }


def inject_jsonld(jsonld_obj):
    with open(INDEX_HTML, "r", encoding="utf-8") as f:
        html = f.read()

    # drop None values (e.g. worksFor if no current job) for a clean payload
    clean = {k: v for k, v in jsonld_obj.items() if v is not None}
    script_block = (
        '<script type="application/ld+json" id="resume-jsonld">\n'
        + json.dumps(clean, indent=2, ensure_ascii=False)
        + "\n</script>"
    )

    pattern = re.compile(
        r'<script type="application/ld\+json" id="resume-jsonld">.*?</script>',
        re.DOTALL,
    )
    if pattern.search(html):
        html = pattern.sub(script_block, html)
    else:
        html = html.replace("</head>", f"  {script_block}\n</head>")

    with open(INDEX_HTML, "w", encoding="utf-8") as f:
        f.write(html)


def main():
    resume = build_resume()

    os.makedirs(os.path.dirname(RESUME_JSON), exist_ok=True)
    with open(RESUME_JSON, "w", encoding="utf-8") as f:
        json.dump(resume, f, indent=2, ensure_ascii=False)
    print(f"Wrote {RESUME_JSON}")

    jsonld = build_jsonld(resume)
    inject_jsonld(jsonld)
    print(f"Updated JSON-LD block in {INDEX_HTML}")


if __name__ == "__main__":
    main()
