Zero-risk workflow (solo dev)

Always commit first

git add -A
git commit -m "wip"   # harmless if nothing to commit

Check ahead/behind before acting

git fetch origin
git status -sb
git log --oneline origin/main..HEAD        # local commits to push
git log --oneline HEAD..origin/main        # remote commits you don't have

If you’re ahead → push

git push origin main

If GitHub is ahead but you’ve got no local commits → pull (fast-forward)

git pull --ff-only

If histories diverged and you want YOUR local to win
(Since you’re solo, this is common after experimenting locally.)

# Optional safety snapshot
git branch backup/$(Get-Date -Format yyyyMMdd-HHmm)

# Make remote match your local branch exactly
git push --force-with-lease origin main