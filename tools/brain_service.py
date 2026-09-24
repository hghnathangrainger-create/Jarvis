"""
brain_service.py

Deterministic, bounded access to Nathan's external Markdown "3D brain"
(a folder of plain Markdown notes linked with [[wikilinks]]), for the
Jarvis AI Operating System.

Responsibilities:
    - Report honest configuration/status: whether BRAIN_ENABLED is on,
      whether BRAIN_PATH is set, whether the root exists, and which of the
      configured allowed subfolders exist (and are genuinely inside the
      configured root).
    - Deterministic, case-insensitive search over filenames, note titles
      (the first Markdown heading), and note content - returning short
      snippets with relative source paths only.
    - Bounded reads of a single note, resolved either by relative path or
      by an exact title/filename match across the allowed folders.
    - Resolved-path validation and atomic writes for the two approval-gated
      write operations (create / update), performed only when explicitly
      asked - this module never writes on its own.

Does NOT:
    - Classify security tiers, create approvals, or execute anything
      (that is SecurityManager/ToolExecutor/ApprovalManager's job).
    - Call AI, the network, or any provider - brain search/read work with
      AI reasoning disabled (or with no API key configured) exactly the
      same as with it enabled.
    - Copy brain notes into SQLite, embed them, or build an index - plain
      deterministic substring matching only, no embeddings/vector store.
    - Ever delete, move, or rename a note. There is no delete operation
      anywhere in this module or in the tools built on it.
    - Scan outside the configured root and the configured allowed
      subfolders. Hidden folders, ".git", "apps" (the 3D-brain visualizer,
      which is NOT knowledge), "node_modules", and other noisy directories
      are always pruned.

Security model (all enforced here, in one place):
    - Only files whose extension is ".md" (case-insensitive) are ever
      considered.
    - Every user-supplied reference is validated lexically (no absolute
      paths, no drive letters, no "..", no hidden segment) and then
      re-checked after Path.resolve(), so a symlink escaping the root or
      the allowed folders is rejected even though its lexical path looks
      innocent.
    - Reads are bounded by BRAIN_MAX_FILE_BYTES; search snippets,
      results, and scanned-file counts are all bounded by fixed module
      constants and BRAIN_SEARCH_LIMIT.
    - Writes (only reached after an approved YELLOW approval) are atomic:
      a temporary file in the destination folder, then os.replace().
"""

from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass
from pathlib import Path

#: The five knowledge subfolders of the real 3D brain, used when
#: BRAIN_FOLDERS is not configured. The visualizer (apps/) is deliberately
#: absent - it is not knowledge and must never be scanned.
DEFAULT_BRAIN_FOLDERS: tuple[str, ...] = (
    "context",
    "decisions",
    "references",
    "audits",
    "brainstorms",
)

#: Defaults mirroring config/settings.py's own BRAIN_* fallbacks.
DEFAULT_MAX_FILE_BYTES = 262_144
DEFAULT_SEARCH_LIMIT = 25
DEFAULT_AI_CONTEXT_CHARS = 4_000

#: Hard safety cap on the number of files inspected in one search, so a
#: pathological tree cannot make a single search run unbounded (mirrors
#: tools/builtin/file_search_tool.py's own _MAX_FILES_SCANNED exactly).
_MAX_FILES_SCANNED = 20_000

#: Maximum length of a search snippet shown for one matching line.
_SNIPPET_CHARS = 200

#: Number of leading bytes sniffed to reject binary files (mirrors
#: FileSearchTool/FileReadTool's own convention).
_SNIFF_BYTES = 4096

#: Directory names always skipped - noisy version-control, cache,
#: virtual-environment, build directories, AND the 3D-brain visualizer
#: ("apps"), which is application code, never knowledge. Exact-name,
#: case-sensitive comparison, plus every hidden (dot-prefixed) name.
_EXCLUDED_DIR_NAMES = frozenset(
    {
        ".git",
        "apps",
        "node_modules",
        "__pycache__",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
        ".venv",
        "venv",
        "env",
        "dist",
        "build",
        ".tox",
    }
)

#: Characters never permitted inside a brain filename or folder name
#: (beyond path/hidden rules) - the Windows-invalid set plus the path
#: separators, rejected up front so a remembered title fails honestly
#: before approval rather than at the filesystem layer after it.
_INVALID_NAME_CHARS = frozenset('<>:"|?*')


class BrainError(Exception):
    """An expected brain-service failure, reported as data by the tools.

    Every predictable problem (disabled, unconfigured, missing root,
    traversal attempt, non-.md target, missing note, duplicate title,
    already-exists on create, missing file on update, oversize content)
    raises this single exception type; the tools convert it into a failed
    ToolResult rather than letting it propagate.
    """


@dataclass(frozen=True, slots=True)
class BrainFolderStatus:
    """Status of one configured allowed subfolder.

    Attributes:
        name: The configured folder name (e.g. "decisions").
        exists: Whether it exists as a directory on disk.
        in_scope: Whether its resolved location is inside the resolved
            root (False means it exists but would never be scanned).
    """

    name: str
    exists: bool
    in_scope: bool


@dataclass(frozen=True, slots=True)
class BrainStatus:
    """Honest snapshot of the brain integration's configuration.

    Attributes:
        enabled: Whether BRAIN_ENABLED is on.
        configured: Whether a non-empty BRAIN_PATH is set.
        root: The configured root, or None when BRAIN_PATH is empty.
        root_exists: Whether the configured root exists as a directory.
        folders: Per-folder status, in configured order. Empty when no
            root is configured (there is nothing to check).
    """

    enabled: bool
    configured: bool
    root: Path | None
    root_exists: bool
    folders: tuple[BrainFolderStatus, ...]


@dataclass(frozen=True, slots=True)
class BrainMatch:
    """One deterministic search hit.

    Attributes:
        rel_path: The note's path relative to the configured root, in
            POSIX form (e.g. "decisions/ship-login.md").
        snippet: A short excerpt - the first matching content line, the
            matching title, or "" for a filename-only match. Never the
            whole file.
    """

    rel_path: str
    snippet: str


@dataclass(frozen=True, slots=True)
class BrainSearchResult:
    """The outcome of one deterministic brain search.

    Attributes:
        query: The query that was searched.
        matches: Hits sorted by relative path (deterministic order),
            truncated to the applied limit.
        limit: The result limit that was applied.
        truncated: True when the limit was reached, so more matches may
            exist beyond those shown.
    """

    query: str
    matches: tuple[BrainMatch, ...]
    limit: int
    truncated: bool


@dataclass(frozen=True, slots=True)
class BrainReadResult:
    """The outcome of one bounded brain-note read.

    Attributes:
        rel_path: The note's path relative to the configured root.
        content: The (possibly truncated) note text.
        truncated: True when the note exceeded BRAIN_MAX_FILE_BYTES and
            only its first BRAIN_MAX_FILE_BYTES bytes were returned.
    """

    rel_path: str
    content: str
    truncated: bool


class BrainService:
    """Deterministic, bounded, read-first access to the Markdown brain.

    A single instance is built in main.py from the already-loaded Settings
    and shared by both brain tools and the optional AI-context builder.
    Constructing it touches no filesystem at all; every method validates
    before it looks.

    Attributes:
        _enabled: BRAIN_ENABLED.
        _root: BRAIN_PATH as a Path, or None when unset/empty.
        _folders: The configured allowed subfolder names, in order.
        _max_file_bytes: Read/scan bound for one note.
        _search_limit: Maximum number of search results.
        _ai_context_chars: Fixed character budget for brain excerpts
            handed to advisory AI reasoning.
    """

    def __init__(
        self,
        *,
        enabled: bool = False,
        root: str | Path | None = None,
        folders: tuple[str, ...] = DEFAULT_BRAIN_FOLDERS,
        max_file_bytes: int = DEFAULT_MAX_FILE_BYTES,
        search_limit: int = DEFAULT_SEARCH_LIMIT,
        ai_context_chars: int = DEFAULT_AI_CONTEXT_CHARS,
    ) -> None:
        """Initialise the service from already-validated configuration.

        Args:
            enabled: BRAIN_ENABLED.
            root: BRAIN_PATH; empty/None means "not configured".
            folders: Allowed subfolder names (already validated by
                config/settings.py when they came from the environment).
            max_file_bytes: Per-note read/scan bound.
            search_limit: Maximum search results.
            ai_context_chars: Combined brain-excerpt budget for AI.
        """
        self._enabled = enabled
        root_str = str(root).strip() if root is not None else ""
        self._root: Path | None = Path(root_str) if root_str else None
        self._folders = tuple(folders) if folders else DEFAULT_BRAIN_FOLDERS
        self._max_file_bytes = max(1, int(max_file_bytes))
        self._search_limit = max(1, int(search_limit))
        self._ai_context_chars = max(1, int(ai_context_chars))

    @property
    def enabled(self) -> bool:
        """Whether BRAIN_ENABLED is on."""
        return self._enabled

    @property
    def configured(self) -> bool:
        """Whether both BRAIN_ENABLED and a BRAIN_PATH are set."""
        return self._enabled and self._root is not None

    @property
    def ai_context_chars(self) -> int:
        """The fixed brain-excerpt character budget for AI context."""
        return self._ai_context_chars

    @property
    def search_limit(self) -> int:
        """The configured maximum number of search results."""
        return self._search_limit

    @property
    def max_file_bytes(self) -> int:
        """The configured per-note read/scan bound in bytes."""
        return self._max_file_bytes

    # ----- status ----------------------------------------------------------

    def status(self) -> BrainStatus:
        """Report honest configuration status without scanning notes.

        Reads only configuration and directory existence; never opens a
        note, never lists file contents, and never exposes any value from
        .env other than the brain path itself.

        Returns:
            A BrainStatus. folders is empty when no root is configured.
        """
        if self._root is None:
            return BrainStatus(
                enabled=self._enabled,
                configured=False,
                root=None,
                root_exists=False,
                folders=(),
            )

        root_resolved = self._root.resolve() if self._root.exists() else self._root
        root_exists = self._root.is_dir()
        folders: list[BrainFolderStatus] = []
        for name in self._folders:
            candidate = self._root / name
            exists = candidate.is_dir()
            in_scope = False
            if exists:
                in_scope = candidate.resolve().is_relative_to(root_resolved)
            folders.append(
                BrainFolderStatus(name=name, exists=exists, in_scope=in_scope)
            )
        return BrainStatus(
            enabled=self._enabled,
            configured=True,
            root=self._root,
            root_exists=root_exists,
            folders=tuple(folders),
        )

    # ----- search ----------------------------------------------------------

    def search(self, query: str) -> BrainSearchResult:
        """Deterministic, case-insensitive search over allowed notes.

        Matches filenames, note titles (first Markdown heading), and note
        content lines. Only .md files inside the configured allowed
        folders are considered; hidden/.git/apps/node_modules folders and
        symlinks are skipped during the walk, oversized and binary files
        are skipped, and the whole scan is bounded by
        _MAX_FILES_SCANNED.

        Args:
            query: The text to search for (case-insensitive substring).

        Returns:
            A BrainSearchResult sorted by relative path.

        Raises:
            BrainError: If the integration is disabled/unconfigured, the
                root does not exist, or the query is empty.
        """
        cleaned = query.strip()
        if not cleaned:
            raise BrainError("Search query must not be empty.")
        return self._search(cleaned, (cleaned.casefold(),))

    def search_any(self, terms: tuple[str, ...] | list[str]) -> BrainSearchResult:
        """Deterministic OR-search across several terms in one tree walk.

        A note matches when ANY non-empty term appears in its filename,
        title, or content - the deterministic multi-term selection used by
        the advisory AI-context builder (plain lexical matching, never
        semantic, never ranked).

        Args:
            terms: The query terms; empty/whitespace-only entries are
                ignored.

        Returns:
            A BrainSearchResult sorted by relative path, whose query is
            the joined terms (for display only).

        Raises:
            BrainError: If the integration is disabled/unconfigured, the
                root does not exist, or no non-empty term was supplied.
        """
        cleaned = [str(term).strip() for term in terms if str(term).strip()]
        if not cleaned:
            raise BrainError("Search query must not be empty.")
        return self._search(" ".join(cleaned), tuple(c.casefold() for c in cleaned))

    def _search(self, display_query: str, matchers: tuple[str, ...]) -> BrainSearchResult:
        """Run one bounded walk matching any of the given matchers.

        Args:
            display_query: The original query, for display only.
            matchers: Non-empty, already-casefolded substrings.

        Returns:
            A BrainSearchResult sorted by relative path.
        """
        root = self._require_scannable_root()

        matches: list[BrainMatch] = []
        scanned = 0
        truncated = False
        limit = self._search_limit

        for rel_path, file_path in self._iter_notes(root):
            scanned += 1
            if scanned > _MAX_FILES_SCANNED:
                truncated = True
                break
            match = self._match_note(file_path, rel_path, matchers)
            if match is None:
                continue
            matches.append(match)
            if len(matches) >= limit:
                truncated = True
                break

        matches.sort(key=lambda item: item.rel_path)
        if truncated:
            matches = matches[:limit]
        return BrainSearchResult(
            query=display_query,
            matches=tuple(matches),
            limit=limit,
            truncated=truncated,
        )

    # ----- read ------------------------------------------------------------

    def read(self, reference: str) -> BrainReadResult:
        """Read one bounded note by relative path or by exact title/name.

        Resolution order (deterministic):
            1. As a relative path inside an allowed folder (with an
               implicit ".md" appended when no extension was given).
            2. As an exact filename or exact note-title match (case-
               insensitive) across the allowed folders. Zero matches is
               an honest "not found"; more than one is an honest
               "ambiguous", listing the candidates - never a guess.

        Args:
            reference: A relative path such as "decisions/ship-login.md",
                or a bare filename/title such as "ship-login".

        Returns:
            A BrainReadResult with content bounded by BRAIN_MAX_FILE_BYTES.

        Raises:
            BrainError: If disabled/unconfigured, the reference escapes
                the root/allowed folders, is not a .md file, is missing,
                is ambiguous, or is unreadable.
        """
        root = self._require_scannable_root()
        cleaned = reference.strip().strip("'\"")
        if not cleaned:
            raise BrainError("Missing note path or title.")

        candidate_rel = cleaned.replace("\\", "/")
        if candidate_rel.startswith("./"):
            candidate_rel = candidate_rel[2:]
        if not candidate_rel:
            raise BrainError("Missing note path or title.")

        # 1. Relative-path resolution - only for references clearly typed
        # as paths (containing "/"). A traversal/hidden/absolute attempt
        # here raises BrainError and is never silently retried as a title,
        # so the rejection is loud and honest.
        if "/" in candidate_rel:
            rel_for_resolve = (
                candidate_rel
                if candidate_rel.casefold().endswith(".md")
                else f"{candidate_rel}.md"
            )
            resolved = self._resolve_within(root, rel_for_resolve)
            if not resolved.is_file():
                raise BrainError(
                    f"No note found at '{rel_for_resolve}' in the allowed "
                    "brain folders."
                )
            return self._read_resolved(root, resolved)

        # 2. Exact filename / exact title lookup across allowed folders.
        lowered = candidate_rel.removesuffix(".md").casefold()
        if not lowered:
            raise BrainError("Missing note path or title.")
        candidates: list[str] = []
        for rel_path, file_path in self._iter_notes(root):
            text = self._read_text_bounded(file_path)
            if text is None:
                continue
            stem = Path(rel_path).stem.casefold()
            title = self._note_title(text).casefold()
            if stem == lowered or title == lowered:
                candidates.append(rel_path)
            if len(candidates) > 1:
                break
        if not candidates:
            raise BrainError(
                f"No note named '{reference.strip()}' exists in the allowed "
                "brain folders."
            )
        if len(candidates) > 1:
            listed = ", ".join(sorted(candidates))
            raise BrainError(
                f"'{reference.strip()}' is ambiguous; it matches: {listed}. "
                "Use the relative path instead."
            )
        resolved = self._resolve_within(root, candidates[0])
        return self._read_resolved(root, resolved)

    # ----- write planning and writing (only ever reached after approval) ---

    def plan_create(self, title: str) -> tuple[str, Path]:
        """Resolve and validate the target for a new note (never writes).

        The title is either a relative path such as
        "decisions/my-note" (placed exactly there) or a bare title such
        as "my-note" (placed in the first configured allowed folder).
        A missing ".md" extension is appended.

        Args:
            title: The requested title or relative path.

        Returns:
            A (rel_path, absolute_path) tuple for the validated target.

        Raises:
            BrainError: If disabled/unconfigured, the title is unsafe,
                the resolved target escapes the root/allowed folders, the
                parent folder does not exist, or the note already exists
                (this never overwrites - use an approved update instead).
        """
        root = self._require_writable_root()
        rel_path = self._title_to_rel_path(title)
        resolved = self._resolve_within(root, rel_path)
        if resolved.exists():
            raise BrainError(
                f"'{rel_path}' already exists. Brain notes are never "
                "overwritten by a create - use 'brain update' instead."
            )
        parent = resolved.parent
        if not parent.is_dir():
            raise BrainError(
                f"Folder '{rel_path.rsplit('/', 1)[0]}' does not exist. "
                "Notes are never created into a folder that is not already "
                "there."
            )
        return rel_path, resolved

    def plan_update(self, rel_reference: str) -> tuple[str, Path]:
        """Resolve and validate the target of an update (never writes).

        Args:
            rel_reference: The relative path of an existing note.

        Returns:
            A (rel_path, absolute_path) tuple for the validated target.

        Raises:
            BrainError: If disabled/unconfigured, the reference escapes
                the root/allowed folders, is not a .md file, or no such
                note exists (updates never create a new note).
        """
        root = self._require_writable_root()
        cleaned = rel_reference.strip().strip("'\"").replace("\\", "/")
        if cleaned.startswith("./"):
            cleaned = cleaned[2:]
        if not cleaned:
            raise BrainError("Missing note relative path.")
        rel_path = cleaned if cleaned.casefold().endswith(".md") else f"{cleaned}.md"
        resolved = self._resolve_within(root, rel_path)
        if not resolved.exists():
            raise BrainError(
                f"'{rel_path}' does not exist. A brain update never creates "
                "a new note; use 'brain remember' for that."
            )
        if resolved.is_symlink():
            raise BrainError(
                f"Refusing to update '{rel_path}': it is a symbolic link, "
                "and brain writes never follow symbolic links."
            )
        if not resolved.is_file():
            raise BrainError(f"'{rel_path}' is not a note file.")
        return rel_path, resolved

    def write(self, target: Path, content: str, *, exclusive: bool = False) -> int:
        """Atomically write note content to an already-validated target.

        This method performs no approval logic of its own - it is only
        ever called by BrainWriteTool.run(), which the Tool Executor
        gates behind an approved YELLOW decision. It re-validates the
        content bound here so an oversized proposal fails honestly.

        Args:
            target: The absolute, already-validated target path.
            content: The full new note content.
            exclusive: When True (a create), refuse if the target exists
                at the moment of the write, so a create can never
                overwrite a note that appeared after planning - an
                update is the only overwrite-shaped operation, and it
                must be its own explicitly approved request.

        Returns:
            The number of bytes written.

        Raises:
            BrainError: If the content is empty or exceeds
                BRAIN_MAX_FILE_BYTES, or if exclusive is set and the
                target already exists.
        """
        if not isinstance(content, str) or not content.strip():
            raise BrainError("Note content must not be empty.")
        data = content.encode("utf-8")
        if len(data) > self._max_file_bytes:
            raise BrainError(
                f"Refusing to write {len(data)} bytes; the limit is "
                f"{self._max_file_bytes} bytes (BRAIN_MAX_FILE_BYTES)."
            )
        if exclusive and target.exists():
            raise BrainError(
                f"'{target.name}' already exists; refusing to overwrite it "
                "with a create."
            )

        parent = target.parent
        fd, temp_name = tempfile.mkstemp(
            dir=str(parent), prefix=".jarvis-brain-", suffix=".tmp"
        )
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_name, str(target))
        except OSError:
            try:
                os.unlink(temp_name)
            except OSError:
                pass
            raise
        return len(data)

    # ----- internals -------------------------------------------------------

    def _require_scannable_root(self) -> Path:
        """Validate enabled/configured/root and return the root.

        Raises:
            BrainError: If disabled, unconfigured, or the root is not an
                existing directory.
        """
        if not self._enabled:
            raise BrainError(
                "Brain integration is disabled. Set BRAIN_ENABLED=true "
                "(and BRAIN_PATH) in your .env file to use brain commands."
            )
        if self._root is None:
            raise BrainError(
                "Brain integration is enabled but not configured: "
                "BRAIN_PATH is not set in your .env file."
            )
        if not self._root.is_dir():
            raise BrainError(
                f"Brain root does not exist or is not a directory: "
                f"{self._root}"
            )
        return self._root

    def _require_writable_root(self) -> Path:
        """Validate the root for a write (identical scoping rules).

        Raises:
            BrainError: Same conditions as _require_scannable_root().
        """
        return self._require_scannable_root()

    def _allowed_dirs(self, root: Path) -> list[tuple[str, Path]]:
        """Return (name, folder) pairs that exist and are inside the root.

        A configured folder that exists but resolves outside the root is
        excluded here - Jarvis never scans outside the configured root.

        Args:
            root: The configured root.

        Returns:
            The scannable allowed folders, in configured order.
        """
        root_resolved = root.resolve()
        allowed: list[tuple[str, Path]] = []
        for name in self._folders:
            folder = root / name
            if folder.is_dir() and folder.resolve().is_relative_to(root_resolved):
                allowed.append((name, folder))
        return allowed

    def _iter_notes(self, root: Path):
        """Yield (rel_path, absolute_path) for scannable .md notes.

        Walks only the configured allowed folders, pruning excluded and
        hidden directory names, never descending into or matching any
        symlinked entry, and only ever yielding regular ".md" files.

        Args:
            root: The configured root.

        Yields:
            (relative POSIX path, absolute path) pairs, folder by folder
            in configured order, each folder walked in sorted order so
            iteration is fully deterministic.
        """
        for _name, folder in self._allowed_dirs(root):
            for dirpath, dirnames, filenames in os.walk(
                folder, followlinks=False
            ):
                dirnames[:] = sorted(
                    d
                    for d in dirnames
                    if d not in _EXCLUDED_DIR_NAMES
                    and not d.startswith(".")
                    and not (Path(dirpath) / d).is_symlink()
                )
                for filename in sorted(filenames):
                    if not filename.casefold().endswith(".md"):
                        continue
                    file_path = Path(dirpath) / filename
                    if file_path.is_symlink() or not file_path.is_file():
                        continue
                    rel = file_path.relative_to(root).as_posix()
                    yield rel, file_path

    def _match_note(
        self, file_path: Path, rel_path: str, matchers: tuple[str, ...]
    ) -> BrainMatch | None:
        """Return one BrainMatch for a note, or None when it does not match.

        Args:
            file_path: The note to inspect.
            rel_path: Its POSIX path relative to root.
            matchers: Already-casefolded substrings; ANY match counts.

        Returns:
            A BrainMatch (content snippet when content matched, title
            snippet when only the title matched, "" for a filename-only
            match), or None when nothing matched or the file is skipped.
        """
        filename = Path(rel_path).name.casefold()
        name_hit = any(matcher in filename for matcher in matchers)

        try:
            if file_path.stat().st_size > self._max_file_bytes:
                return None
        except OSError:
            return None

        text = self._read_text_bounded(file_path)
        if text is None:
            return None
        title = self._note_title(text)
        lowered_text = text.casefold()
        lowered_title = title.casefold()

        snippet: str | None = None
        for matcher in matchers:
            if matcher in lowered_text:
                snippet = self._first_matching_line(text, matcher)
                break
        if snippet is None:
            if any(matcher in lowered_title for matcher in matchers):
                snippet = title
            elif name_hit:
                snippet = ""
            else:
                return None
        return BrainMatch(rel_path=rel_path, snippet=snippet)

    def _read_text_bounded(self, file_path: Path) -> str | None:
        """Read one note's text, bounded and binary-safe.

        Args:
            file_path: The note to read.

        Returns:
            The decoded text (at most BRAIN_MAX_FILE_BYTES bytes), or
            None when the file is binary or unreadable for any reason.
        """
        try:
            if file_path.is_symlink() or not file_path.is_file():
                return None
            with file_path.open("rb") as handle:
                sniff = handle.read(_SNIFF_BYTES)
                if b"\x00" in sniff:
                    return None
                handle.seek(0)
                data = handle.read(self._max_file_bytes)
            return data.decode("utf-8", errors="replace")
        except OSError:
            return None

    @staticmethod
    def _note_title(text: str) -> str:
        """Return the first Markdown heading of a note, or "".

        Args:
            text: The note's text.

        Returns:
            The first line starting with "#", stripped of its leading
            hashes and whitespace, or "" when the note has no heading.
        """
        for line in text.splitlines():
            stripped = line.strip()
            if stripped.startswith("#"):
                return stripped.lstrip("#").strip()
        return ""

    @staticmethod
    def _first_matching_line(text: str, lowered_query: str) -> str:
        """Return a bounded excerpt of the first content line matching.

        Args:
            text: The note's text.
            lowered_query: The already-casefolded query.

        Returns:
            The first matching line stripped and bounded to
            _SNIPPET_CHARS (with an honest "..." marker), or "" when no
            single line matches (e.g. the match spans lines).
        """
        for line in text.splitlines():
            if lowered_query in line.casefold():
                stripped = line.strip()
                if len(stripped) > _SNIPPET_CHARS:
                    return stripped[:_SNIPPET_CHARS] + "..."
                return stripped
        return ""

    def _title_to_rel_path(self, title: str) -> str:
        """Convert a remember-title into a validated relative .md path.

        Args:
            title: The raw title token from the command.

        Returns:
            The validated relative POSIX path.

        Raises:
            BrainError: If the title is empty or unsafe (absolute, drive
                letter, "..", hidden segment, invalid filename character).
        """
        cleaned = title.strip().strip("'\"").replace("\\", "/")
        if cleaned.startswith("./"):
            cleaned = cleaned[2:]
        if not cleaned:
            raise BrainError("Missing note title.")
        if "/" not in cleaned:
            cleaned = f"{self._folders[0]}/{cleaned}"
        if not cleaned.casefold().endswith(".md"):
            cleaned = f"{cleaned}.md"
        self._validate_rel_path(cleaned)
        return cleaned

    @staticmethod
    def _validate_rel_path(rel_path: str) -> None:
        """Reject any relative path that is not a safe in-root path.

        Args:
            rel_path: The candidate POSIX relative path.

        Raises:
            BrainError: If the path is absolute, has a drive letter,
                contains "..", contains a hidden segment, or contains a
                character invalid in a filename.
        """
        candidate = Path(rel_path)
        if candidate.is_absolute() or candidate.drive or rel_path.startswith("/"):
            raise BrainError(
                f"'{rel_path}' is not a relative brain path; absolute paths "
                "are never accepted."
            )
        for segment in candidate.parts:
            if segment == "..":
                raise BrainError(
                    "Path traversal ('..') is never accepted in brain paths."
                )
            if segment.startswith("."):
                raise BrainError(
                    f"'{segment}' is a hidden name and is never part of the "
                    "brain scope."
                )
            if any(ch in _INVALID_NAME_CHARS for ch in segment):
                raise BrainError(
                    f"'{segment}' contains characters that are never allowed "
                    "in a brain path."
                )
        if not rel_path.casefold().endswith(".md"):
            raise BrainError(f"'{rel_path}' is not a Markdown (.md) note.")

    def _resolve_within(self, root: Path, rel_path: str) -> Path:
        """Resolve rel_path and prove it stays inside root/allowed folders.

        Lexical validation runs first (via _validate_rel_path), then the
        resolved path must be inside the resolved root AND inside one of
        the configured allowed folders - so a symlink whose target escapes
        the root (or points at a non-allowed part of the tree) is rejected
        even though its lexical path looks innocent.

        Args:
            root: The configured root.
            rel_path: The already lexically-validated relative path.

        Returns:
            The resolved absolute path.

        Raises:
            BrainError: If the resolved path escapes the root or the
                allowed folders.
        """
        self._validate_rel_path(rel_path)
        resolved = (root / rel_path).resolve()
        root_resolved = root.resolve()
        if not resolved.is_relative_to(root_resolved):
            raise BrainError(
                f"'{rel_path}' resolves outside the configured brain root; "
                "it was rejected."
            )
        rel_resolved = resolved.relative_to(root_resolved)
        top_folder = rel_resolved.parts[0] if rel_resolved.parts else ""
        if top_folder not in self._folders:
            raise BrainError(
                f"'{rel_path}' is outside the configured brain folders "
                f"({', '.join(self._folders)}); it was rejected."
            )
        return resolved

    @staticmethod
    def _rel_path(root: Path, file_path: Path) -> str:
        """Return file_path relative to root in POSIX form.

        Args:
            root: The configured root.
            file_path: The absolute file path.

        Returns:
            The POSIX-style relative path, or the absolute path string
            when it cannot be expressed relatively (defensive only).
            Both the root and the file are resolved before comparing, so
            a root typed with a drive-letter short name (or any other
            unnormalised spelling) still yields a genuinely relative
            source path.
        """
        for base in (root, root.resolve()):
            try:
                return file_path.relative_to(base).as_posix()
            except ValueError:
                continue
        return file_path.as_posix()

    def _read_resolved(self, root: Path, resolved: Path) -> BrainReadResult:
        """Read one already-validated note with the configured bound.

        Args:
            root: The configured root.
            resolved: The resolved absolute path of the note.

        Returns:
            A BrainReadResult; truncated is True when the note exceeded
            BRAIN_MAX_FILE_BYTES and only the first bound was returned.

        Raises:
            BrainError: If the note cannot be read.
        """
        rel_path = self._rel_path(root, resolved)
        try:
            size = resolved.stat().st_size
            with resolved.open("rb") as handle:
                data = handle.read(self._max_file_bytes)
        except OSError as exc:
            raise BrainError(f"Could not read '{rel_path}': {exc}") from exc
        if b"\x00" in data[:_SNIFF_BYTES]:
            raise BrainError(f"'{rel_path}' does not look like a text note.")
        content = data.decode("utf-8", errors="replace")
        return BrainReadResult(
            rel_path=rel_path,
            content=content,
            truncated=size > len(data),
        )
