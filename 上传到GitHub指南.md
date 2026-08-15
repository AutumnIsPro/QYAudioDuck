# 上传到 GitHub 指南 (AutumnIsPro/QYAudioDuck)

你的仓库：`https://github.com/AutumnIsPro/QYAudioDuck`（公开、空仓库，默认分支 main）

## 一、安装 Git（只需一次）

1. 打开 <https://git-scm.com/download/win> 下载 Git for Windows
2. 双击安装，一路「Next」（默认选项即可）
3. 安装完成后**重新打开命令行窗口**（或直接双击项目里的 `git-upload.bat`）

## 二、方式 A：双击脚本自动上传（推荐）

1. 打开项目文件夹 `E:\MyProjects\test\AudioDuck`
2. **双击 `git-upload.bat`**
3. 脚本会自动：
   - 初始化 git 仓库（若还没有）
   - 关联你的远程仓库
   - 添加所有文件（`.gitignore` 已自动排除 `.venv`、`build`、`dist`、`__pycache__` 等）
   - 提交（首次会询问你的 GitHub 用户名和邮箱）
   - 推送
4. **推送时会弹出 GitHub 登录窗口**（浏览器授权，或要求输入用户名 + Token）→ 登录一次即可
5. 看到 `[DONE] Uploaded` 就成功了，刷新你的 GitHub 页面即可看到代码

## 三、方式 B：手动命令（了解原理）

```bat
cd /d E:\MyProjects\test\AudioDuck
git init -b main
git remote add origin https://github.com/AutumnIsPro/QYAudioDuck.git
git config user.name "AutumnIsPro"
git config user.email "你的GitHub邮箱"
git add -A
git commit -m "Audio Duck v1.0.0 - 音频自动闪避助手"
git push -u origin main
```

## 四、GitHub 登录（推送时的关键一步）

首次 `git push` 时，Git for Windows 自带的「凭据管理器」会：

- **弹出浏览器**让你登录 GitHub → 点 Authorize 即可；或
- 弹出窗口要求输入 **Username** 和 **Password**（这里的 Password 填的不是登录密码，而是 **Personal Access Token**）：
  1. 打开 <https://github.com/settings/tokens> → Generate new token (classic)
  2. 勾选 `repo` 权限，生成后**复制**（只显示一次）
  3. 粘贴到密码框

登录成功后凭据会被记住，以后推送不再要求。

## 五、哪些文件会上传 / 不会上传

**会上传**：所有 `.py`、`.bat`、`.vbs`、`.ps1`、`icon.ico`、`requirements.txt`、`README.md`、`.gitignore`、`make_icon.py`、`114514` 图片文件夹（约 19MB）

**自动排除**（`.gitignore` 已配置）：`.venv`（98MB）、`build`、`dist`、`__pycache__`、`*.spec`、`error.log`

> ⚠️ 注意：你的仓库是**公开**的，`114514` 里的 4 张图片会被所有人看到。如果介意，可先删除该文件夹（应用会自动用深色渐变背景），或换成自己的占位图。

## 六、结合自动更新（可选，强烈推荐）

仓库上传后，把 GitHub Releases 作为更新源：

1. 每次发布新版：到仓库页面 → **Releases** → **Draft a new release** → 上传 `dist\AudioDuck.exe`，填版本号（如 v1.1.0）
2. 把 `version.json` 更新为：
   ```json
   {
     "version": "1.1.0",
     "url": "https://github.com/AutumnIsPro/QYAudioDuck/releases/download/v1.1.0/AudioDuck.exe",
     "notes": "本次更新内容"
   }
   ```
3. 把这个 `version.json` 也提交到仓库 `main` 分支，并把 `updater.py` 里的 `UPDATE_URL` 改成：
   ```
   https://raw.githubusercontent.com/AutumnIsPro/QYAudioDuck/main/version.json
   ```
4. 重新打包 exe 发给别人 → 之后每次发新版，旧版用户打开就会自动更新

## 七、以后更新代码

改完代码后，再双击 `git-upload.bat` 即可（自动提交并推送新版本）。
