# /resume-claude — Resume Interrupted Claude Code / OMC Session

## Trigger
- Slash command: `/resume-claude`
- Keywords: "resume claude", "claude 이어받기", "이어서 작업", "rate limit"

## Purpose
Import an interrupted Claude Code or OMC session so GitHub Copilot can continue the work seamlessly. Handles both OMC (full state import) and vanilla Claude Code (lossy JSONL import).

## Workflow

### Step 1 — Detect
Call `omg_detect_external_session` to scan for available sessions.

If no sessions found:
> "외부 세션을 찾을 수 없습니다. `.omc/` 디렉토리나 `~/.claude/projects/` 의 JSONL 파일이 존재하는지 확인해주세요."

### Step 2 — Compare
Call `omg_compare_checkpoints` to show timestamps side-by-side.

Display to user:
```
현재 OMG 체크포인트: {timestamp or "없음"}
외부 세션:
  - {source}: {timestamp} {newer_than_omg ? "← 더 최신" : ""}
```

### Step 3 — Confirm
Use `vscode_askQuestions` to confirm import:

```
header: "resume-external"
question: "외부 세션을 import하시겠습니까?"
options:
  - label: "{source} 세션 이어받기"
    description: "{timestamp}, {details}"
    recommended: true
  - label: "취소"
allowFreeformInput: false
```

If multiple sources exist, let user pick which one.

### Step 4 — Import
Call `omg_import_external_session` with the selected source.

- If OMG checkpoint already exists and is newer, warn but allow `force: true`
- Previous checkpoint is automatically backed up to `session-checkpoint.previous.json`

### Step 5 — Summarize
Display the imported checkpoint summary:

```
✅ {source} 세션 import 완료

📋 Import 결과:
- 소스: {source} (세션 {session_id})
- Import된 파일: {imported_files count}개
- 충돌 건너뜀: {conflicts count}개

📝 마지막 작업 요약:
{imported_summary}

📁 수정된 파일:
{modified_files list}
```

### Step 6 — Continue
Ask the user what to do next:
```
header: "resume-next-action"
question: "어떤 작업부터 이어갈까요?"
options:
  - label: "마지막 작업 이어서 진행"
    recommended: true
  - label: "PRD/Story 상태 확인"
  - label: "수정된 파일 리뷰"
  - label: "새로운 작업 시작"
```

## Error Handling
- If JSONL parsing fails partially: show what was extracted, note incomplete import
- If `.omc/` state files are corrupted: skip corrupted files, import what works
- If checkpoint backup fails: abort import, do not overwrite

## Notes
- OMC imports are lossless (same schema)
- Claude Code JSONL imports are lossy — extracts user intent, modified files, and assistant summary
- Checkpoint file permissions are set to 0600 for privacy
- The imported checkpoint includes `source_tool`, `source_session_id`, `imported_at` metadata for provenance tracking
