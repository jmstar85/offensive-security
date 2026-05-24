#!/usr/bin/env bash
# GitHub Copilot Chat 이력 마이그레이션 (chrisjung Mac mini → minsung.jung MacBook Pro)
#
# 동작:
#   1. VSCode가 실행 중이면 중단 (state.vscdb 충돌 방지)
#   2. 워크스페이스 매핑마다 다음 처리:
#        - chatSessions/, chatEditingSessions/, GitHub.copilot-chat/ 를 cp -n 으로 병합
#        - state.vscdb 의 chat.ChatSessionStore.index 를 SRC 항목과 병합 (DST 우선 보존)
#   3. 처리 전 자동 백업 생성 (디렉터리 .bak.<timestamp>, state.vscdb.bak.<timestamp>)
#
# 사용:
#   1. VSCode 완전 종료 (⌘Q)
#   2. bash migrate_copilot_history.sh           # 모든 매핑 처리
#      bash migrate_copilot_history.sh offsec    # offensive-security 만
#      bash migrate_copilot_history.sh --dry-run # 변경 없이 계획만 출력
#
# 매핑(편집 가능):
#   - chrisjung workspaceStorage 폴더 ID → minsung.jung workspaceStorage 폴더 ID
#   - 새 매핑은 MAPPING 배열에 "label|src_id|dst_id" 형식으로 추가

set -euo pipefail

WS_ROOT="$HOME/Library/Application Support/Code/User/workspaceStorage"
STAMP=$(date +%Y%m%d-%H%M%S)
DRY_RUN=0

MAPPING=(
  "offsec|3b4b551c7853c4a868c2e10987a3406a|4ed5eb4f54ab7561e1cd017bcf7c2ce2"
  "myproject|24893cfd65fc9503dcbda01544b63eda|c0394f27aeaf26ba46438ebd531068f8"
  "vscode-omg|5331f55f41e04e56f260b4f9409a6982|8fe332b4dafa52099249bf556717ef27"
  "ReiYoung_Yoga|62f8cdec82459d3a9f6118cd87dc1117|83a5c008cd80080659469cc048c8c673"
  "oh-my-githubcopilot|e55fe1af40f31e96810a2d60146059f5|2d9cecb493a1adfd1e46c60b25089a10"
  ".claude|eb3229b0b4135fd3a0d9b364ad4bf523|1abc2fa42ca7cefb54ee333f348e0d52"
  ".hermes|b47f4c1d7fea87fc43eb92d487b1517d|be1b666e60a36dc736a41b6b0694c55d"
)

log()  { printf "\033[36m[i]\033[0m %s\n" "$*"; }
warn() { printf "\033[33m[!]\033[0m %s\n" "$*"; }
err()  { printf "\033[31m[x]\033[0m %s\n" "$*" >&2; }
ok()   { printf "\033[32m[o]\033[0m %s\n" "$*"; }

if [[ "${1:-}" == "--dry-run" ]]; then DRY_RUN=1; shift; fi
FILTER="${1:-}"

if pgrep -fl "Visual Studio Code.app" >/dev/null 2>&1; then
  err "VSCode가 실행 중입니다. 완전히 종료(⌘Q)한 뒤 다시 실행하세요."
  err "Claude Code 확장도 같이 꺼지므로 터미널에서 실행하셔야 합니다."
  exit 1
fi

if ! command -v sqlite3 >/dev/null; then err "sqlite3가 필요합니다."; exit 1; fi
if ! command -v python3  >/dev/null; then err "python3가 필요합니다.";  exit 1; fi

merge_workspace() {
  local label="$1" src_id="$2" dst_id="$3"
  local SRC="$WS_ROOT/$src_id" DST="$WS_ROOT/$dst_id"

  echo
  log "=== [$label]  $src_id → $dst_id ==="

  [[ -d "$SRC" ]] || { warn "SRC 없음 — 건너뜀: $SRC"; return; }
  [[ -d "$DST" ]] || { warn "DST 없음 — 건너뜀: $DST"; return; }

  for sub in chatSessions chatEditingSessions GitHub.copilot-chat; do
    if [[ -d "$SRC/$sub" ]]; then
      if [[ $DRY_RUN -eq 1 ]]; then
        log "(dry) cp -Rn $SRC/$sub/* → $DST/$sub/"
      else
        mkdir -p "$DST/$sub"
        if [[ -d "$DST/$sub" && -n "$(ls -A "$DST/$sub" 2>/dev/null)" ]]; then
          cp -a "$DST/$sub" "$DST/$sub.bak.$STAMP" 2>/dev/null || true
        fi
        cp -Rn "$SRC/$sub/"* "$DST/$sub/" 2>/dev/null || true
        ok "복사 완료: $sub"
      fi
    fi
  done

  if [[ ! -f "$SRC/state.vscdb" ]]; then
    warn "SRC state.vscdb 없음 — 인덱스 병합 생략"
    return
  fi
  if [[ ! -f "$DST/state.vscdb" ]]; then
    if [[ $DRY_RUN -eq 1 ]]; then
      log "(dry) cp $SRC/state.vscdb → $DST/state.vscdb"
    else
      cp -a "$SRC/state.vscdb" "$DST/state.vscdb"
      ok "DST에 state.vscdb 없어 SRC 전체 복사"
    fi
    return
  fi

  local SRC_IDX DST_IDX MERGED_IDX
  SRC_IDX=$(sqlite3 "$SRC/state.vscdb" "SELECT value FROM ItemTable WHERE key='chat.ChatSessionStore.index';" 2>/dev/null || echo "")
  DST_IDX=$(sqlite3 "$DST/state.vscdb" "SELECT value FROM ItemTable WHERE key='chat.ChatSessionStore.index';" 2>/dev/null || echo "")

  if [[ -z "$SRC_IDX" ]]; then warn "SRC 인덱스 비어있음 — 생략"; return; fi

  MERGED_IDX=$(python3 - "$SRC_IDX" "$DST_IDX" <<'PY'
import sys, json
src_raw, dst_raw = sys.argv[1], sys.argv[2]
src = json.loads(src_raw) if src_raw else {"version":1,"entries":{}}
dst = json.loads(dst_raw) if dst_raw else {"version":1,"entries":{}}
src_e = src.get("entries", {})
dst_e = dst.get("entries", {})
added, kept = 0, 0
for k, v in src_e.items():
    if k in dst_e:
        kept += 1
    else:
        dst_e[k] = v
        added += 1
dst["entries"] = dst_e
sys.stderr.write(f"added={added} kept_dst={kept} total={len(dst_e)}\n")
print(json.dumps(dst, ensure_ascii=False))
PY
)

  if [[ $DRY_RUN -eq 1 ]]; then
    log "(dry) state.vscdb 인덱스 UPDATE 계획됨"
    return
  fi

  cp -a "$DST/state.vscdb" "$DST/state.vscdb.bak.$STAMP"

  python3 - "$DST/state.vscdb" "$MERGED_IDX" <<'PY'
import sqlite3, sys
db, val = sys.argv[1], sys.argv[2]
conn = sqlite3.connect(db)
conn.execute(
    "INSERT INTO ItemTable(key,value) VALUES('chat.ChatSessionStore.index', ?) "
    "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
    (val,)
)
conn.commit()
conn.close()
print("state.vscdb 인덱스 UPDATE 완료")
PY
  ok "인덱스 병합 완료"
}

if [[ -n "$FILTER" ]]; then
  found=0
  for m in "${MAPPING[@]}"; do
    IFS='|' read -r label src dst <<<"$m"
    if [[ "$label" == "$FILTER" ]]; then merge_workspace "$label" "$src" "$dst"; found=1; fi
  done
  [[ $found -eq 0 ]] && { err "라벨 없음: $FILTER"; exit 1; }
else
  for m in "${MAPPING[@]}"; do
    IFS='|' read -r label src dst <<<"$m"
    merge_workspace "$label" "$src" "$dst"
  done
fi

echo
ok "모두 완료. VSCode를 다시 켜고 Copilot Chat → Show Chats 에서 확인하세요."
log "롤백이 필요하면 각 워크스페이스의 *.bak.$STAMP 파일을 원래대로 되돌리면 됩니다."
