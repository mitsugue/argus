#!/usr/bin/env bash
# 図形認証コードの画像を要求する(OpenDログインで求められた時)。
# 画像は OpenD の実行ディレクトリに PicVerifyCode.png として保存される。
set -uo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$DIR/_redact.sh"; source "$DIR/_telnet.sh"

echo "== req_pic_verify_code 送信 =="
opend_cmd 'req_pic_verify_code' 3 | redact

PNG="$(find /home/ubuntu -maxdepth 3 -name 'PicVerifyCode.png' -newermt '-10 minutes' 2>/dev/null | head -1)"
echo ""
if [ -n "${PNG:-}" ]; then
  echo "OK: 画像生成: $PNG"
else
  echo "画像が見つからない場合は ~/.com.moomoo.OpenD/F3CNN/PicVerifyCode.png を確認(10.11.7108 の置き場)。"
  PNG="/home/ubuntu/.com.moomoo.OpenD/F3CNN/PicVerifyCode.png"
fi
echo ""
echo "Macから取得(Mac側で実行):"
echo "  scp ubuntu@52.195.168.61:$PNG ~/Desktop/"
echo "画像の文字を確認したら submit_pic_verify_code.sh を実行(コードは画面に出ません)。"
echo "⚠ 入力を間違えたら古い画像は失効 — このスクリプトで新しい画像を取り直すこと。"
echo "⚠ 画像は短い時間で失効する(2026-10-24 は数分かけると毎回 incorrect)— 取ったらすぐに入力すること。"
