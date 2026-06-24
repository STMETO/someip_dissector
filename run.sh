#!/bin/bash
# ===================================================================
# SOME/IP Dissector — 统一启动脚本
# ===================================================================

set -e
cd "$(dirname "$0")"

CMD="${1:-}"

# ---- 无参数 / help ----
if [[ -z "$CMD" || "$CMD" == "-h" || "$CMD" == "--help" || "$CMD" == "help" ]]; then
  cat << 'EOF'
SOME/IP Dissector — 统一启动脚本

用法:
  ./run.sh web              启动 Web 界面 (http://localhost:8000)
  ./run.sh debug [选项]     debug模式

测试文件位置:
  项目test目录下的 sample.pcap 和 sample.arxml
  或通过 debug 模式的 --pcap / --arxml 参数指定
EOF
  exit 0
fi

case "$CMD" in

  web)
    # 自动释放端口：杀掉旧的 uvicorn / start.py 进程
    pkill -f "uvicorn.*web.backend" 2>/dev/null || true
    pkill -f "web/start.py" 2>/dev/null || true
    sleep 1

    echo "=== 启动 Web 界面 ==="
    echo "    浏览器打开 http://localhost:8000"
    echo ""
    python web/start.py
    ;;

  debug)
    shift
    python test/main.py "$@"
    ;;

  *)
    echo "未知命令: $CMD"
    echo "请使用 ./run.sh --help 查看用法"
    exit 1
    ;;
esac
