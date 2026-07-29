"""Map file extensions to languages and report what could not be classified."""

from pathlib import PurePosixPath

EXT_LANGUAGE = {
    ".py": "python", ".go": "go", ".rs": "rust", ".rb": "ruby",
    ".ts": "typescript", ".tsx": "typescript",
    ".js": "javascript", ".jsx": "javascript", ".mjs": "javascript",
    ".java": "java", ".kt": "kotlin", ".kts": "kotlin",
    ".cs": "csharp", ".php": "php", ".swift": "swift", ".scala": "scala",
    ".ex": "elixir", ".exs": "elixir", ".erl": "erlang",
    ".c": "c", ".h": "c", ".cpp": "cpp", ".cc": "cpp", ".hpp": "cpp",
    ".sh": "shell", ".bash": "shell", ".sql": "sql", ".lua": "lua",
    ".dart": "dart", ".clj": "clojure", ".hs": "haskell",
}

IGNORABLE_EXTS = {
    ".md", ".rst", ".txt", ".json", ".yml", ".yaml", ".toml", ".ini",
    ".cfg", ".conf", ".lock", ".csv", ".tsv", ".xml", ".html", ".htm",
    ".css", ".scss", ".less", ".svg", ".png", ".jpg", ".jpeg", ".gif",
    ".ico", ".webp", ".pdf", ".woff", ".woff2", ".ttf", ".eot",
    ".gitignore", ".gitattributes", ".editorconfig", ".env", ".example",
    ".mod", ".sum", ".log", ".zip", ".gz", ".tar",
}


def classify_languages(paths):
    """Return (language records, paths with an unrecognized source extension)."""
    counts = {}
    unknown = []
    for path in paths:
        ext = PurePosixPath(path).suffix.lower()
        language = EXT_LANGUAGE.get(ext)
        if language:
            counts[language] = counts.get(language, 0) + 1
        elif ext and ext not in IGNORABLE_EXTS:
            unknown.append(path)
    total = sum(counts.values())
    languages = [
        {
            "name": name,
            "files": count,
            "share": round(count / total, 3) if total else 0.0,
        }
        for name, count in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    ]
    return languages, unknown
