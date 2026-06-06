#!/usr/bin/env bash
# cgroup_memory_limit.sh - Apply cgroup memory limits to key processes
# Usage: sudo bash scripts/cgroup_memory_limit.sh [apply|status|cleanup]
set -euo pipefail

CGROUP_ROOT="/sys/fs/cgroup/memory/GenericAgent"

# Process definitions: name pid_limit_mb
PROCESSES=(
    "hermes:706028:500"
    "nanobot:732218:200"
    "fsapp:706150:256"
    "reflect:706174:128"
)

apply() {
    echo "=== Creating cgroups and setting limits ==="
    for entry in "${PROCESSES[@]}"; do
        IFS=':' read -r name pid limit_mb <<< "$entry"
        limit_bytes=$((limit_mb * 1024 * 1024))
        
        mkdir -p "$CGROUP_ROOT/$name" 2>/dev/null || true
        echo "$limit_bytes" > "$CGROUP_ROOT/$name/memory.limit_in_bytes" 2>/dev/null || {
            echo "  [ERROR] Failed to set limit for $name (need root)"
            return 1
        }
        # Move PID into cgroup (if process still exists)
        if [ -d "/proc/$pid" ]; then
            echo "$pid" > "$CGROUP_ROOT/$name/cgroup.procs" 2>/dev/null || true
        fi
        
        current=$(cat "$CGROUP_ROOT/$name/memory.usage_in_bytes" 2>/dev/null || echo 0)
        echo "  $name (PID=$pid): limit=${limit_mb}MB current=$((current / 1024 / 1024))MB"
    done
    echo "✅ cgroup limits applied"
}

status() {
    echo "=== GenericAgent cgroup memory status ==="
    if [ ! -d "$CGROUP_ROOT" ]; then
        echo "No cgroup hierarchy found"
        return 1
    fi
    for entry in "${PROCESSES[@]}"; do
        IFS=':' read -r name pid limit_mb <<< "$entry"
        cg_dir="$CGROUP_ROOT/$name"
        if [ -d "$cg_dir" ]; then
            usage=$(cat "$cg_dir/memory.usage_in_bytes" 2>/dev/null || echo 0)
            limit=$(cat "$cg_dir/memory.limit_in_bytes" 2>/dev/null || echo 0)
            pids_in_cg=$(cat "$cg_dir/cgroup.procs" 2>/dev/null || echo "")
            oom=$(cat "$cg_dir/memory.oom_control" 2>/dev/null | grep "oom_kill" || echo "")
            echo "  $name: usage=$((usage/1024/1024))MB / limit=$((limit/1024/1024))MB pids=$pids_in_cg $oom"
        else
            echo "  $name: NOT CONFIGURED"
        fi
    done
}

cleanup() {
    echo "=== Cleaning up cgroups ==="
    for entry in "${PROCESSES[@]}"; do
        IFS=':' read -r name pid limit_mb <<< "$entry"
        # Move processes back to root cgroup
        if [ -d "$CGROUP_ROOT/$name" ] && [ -f "$CGROUP_ROOT/$name/cgroup.procs" ]; then
            while read -r p; do
                [ -n "$p" ] && echo "$p" > /sys/fs/cgroup/memory/cgroup.procs 2>/dev/null || true
            done < "$CGROUP_ROOT/$name/cgroup.procs"
            rmdir "$CGROUP_ROOT/$name" 2>/dev/null || true
        fi
    done
    rmdir "$CGROUP_ROOT" 2>/dev/null || true
    echo "✅ Cleanup done"
}

case "${1:-status}" in
    apply) apply ;;
    status) status ;;
    cleanup) cleanup ;;
    *)
        echo "Usage: $0 [apply|status|cleanup]"
        exit 1
        ;;
esac
