python -m http.server

git add latest_data.json
git commit -m "update"
git config pull.rebase false
git pull
git push
