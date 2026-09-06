import en, { type MessageKey } from "./en";

const zhCN: Record<MessageKey, string> = {
  ...en,
  "app.brand": "AUTOPILOT",
  "app.brand.sub": "仪表板",
  "nav.episodes": "剧集",
  "status.idle": "空闲",
  "status.job": "任务",
  "language.selector.label": "语言",
  "greeting.welcome": "欢迎回来，{{name}}",
  "nav.back": "← 返回剧集", "nav.list": "← 返回列表", "episodes.heading": "剧集", "episodes.count": "{{count}} 集", "episodes.new": "+ 新建剧集",
  "common.loading": "加载中…", "common.open": "打开", "common.none": "无", "common.save": "保存", "common.saved": "已保存", "common.remove": "移除", "common.previous": "← 上一步", "common.next": "下一步", "common.download": "下载", "common.play": "▶ 播放",
  "episodes.empty": "暂无剧集文件", "episodes.emptyAction": "打开新建剧集向导", "episodes.columns.number": "剧集", "episodes.columns.title": "标题", "episodes.columns.parts": "段落", "episodes.columns.status": "状态", "episodes.columns.lastRun": "上次运行", "episodes.columns.duration": "时长", "episodes.columns.actions": "操作", "episode.example": "示例", "status.ok": "正常", "status.err": "错误", "status.live": "实时 SSE",
  "new.heading": "新建剧集",
  "new.navTag": "/ 新建剧集", "new.basic": "基本信息", "new.basicHint": "沿用最近剧集的标签作为起点", "new.parts": "段落音频", "new.partsHint": "{{count}} 个文件 · {{duration}} · 可重新排序", "new.assets": "配乐与章节", "new.optional": "全部可选", "new.nextParts": "下一步：添加段落 →", "new.nextAssets": "下一步：配乐与章节 →", "new.create": "创建剧集", "new.createRun": "创建并立即运行 →", "new.creating": "创建中…", "new.dropAudio": "将音频文件拖到此处，或点击选择", "new.registerPath": "注册路径", "new.addAsset": "添加 {{name}} 音频", "new.assetIntro": "片头", "new.assetOutro": "片尾", "new.assetBgm": "配乐", "new.notAdded": "尚未添加", "new.addChapter": "＋ 添加章节", "new.chapterTitle": "章节标题",
  "detail.heading": "剧集详情", "detail.review": "查看波形", "detail.clips": "片段候选", "detail.deliverables": "成品文件", "controls.profile": "配置文件", "controls.model": "模型", "controls.force": "强制重新运行", "controls.skip": "跳过阶段", "controls.skipped": "{{count}} 个阶段", "controls.run": "运行", "controls.cancel": "取消", "controls.fast": "快速", "controls.accurate": "精准", "stage.heading": "阶段网格", "stage.part": "段落", "stage.assembly": "[剧集合成]", "stage.status.running": "执行中…", "stage.status.ran": "完成 {{elapsed}}s", "stage.status.ranPlain": "完成", "stage.status.cached": "已缓存", "stage.status.skipped": "已跳过", "stage.status.failed": "失败", "stage.status.cancelled": "已取消", "log.heading": "实时日志输出", "log.lines": "（{{count}}/200 行）", "log.pause": "悬停时暂停", "log.collapse": "收起", "log.expand": "展开", "log.empty": "暂无日志…", "transcript.heading": "文字稿", "transcript.search": "搜索…", "transcript.noResults": "没有匹配结果",
  "items.heading": "编辑项目", "items.select": "j/k 选择", "items.listen": "空格键试听", "items.toggle": "e 切换", "items.enabled": "已启用", "items.kind": "类型", "items.start": "开始", "items.end": "结束", "items.reason": "原因", "items.keep": "保留", "items.fade": "淡出", "review.unsaved": "● 未保存", "review.leaveConfirm": "有未保存的更改，仍要离开吗？", "review.switchConfirm": "切换段落会丢弃未保存的更改，继续吗？", "review.failed": "查看失败（422）：", "review.saveApply": "保存并应用", "review.cut": "剪除", "review.filler": "赘字", "review.clip": "片段候选", "review.zoom": "滚动缩放 · 拖动平移", "report.heading": "运行报告", "report.empty": "尚未生成 RUN_REPORT.md，请先运行处理流程。",
  "clips.heading": "片段候选",
  "clips.navTag": "/ 片段",
  "clips.duration": "时长", "clips.generate": "生成候选", "clips.generateRender": "生成并渲染", "clips.part": "段落", "clips.count": "{{count}} 个候选", "clips.notGenerated": "暂无候选", "clips.generating": "正在生成候选…", "clips.generatingRender": "正在生成候选并渲染文件…", "clips.running": "任务运行中 · SSE 实时", "clips.rank": "排名", "clips.window": "区间", "clips.score": "分数", "clips.excerpt": "摘录", "clips.actions": "操作", "deliverables.heading": "成品文件", "deliverables.loading": "加载成品文件…", "deliverables.none": "暂无最终 MP3，请先运行完整处理流程。", "deliverables.final": "最终输出", "deliverables.downloadMp3": "下载 MP3", "deliverables.chapters": "章节", "deliverables.editedParts": "已编辑段落", "deliverables.notProduced": "尚未生成", "deliverables.openReport": "打开 RUN_REPORT.md", "deliverables.truePeak": "真实峰值：{{value}}",
  "review.fillerSummary": "启用赘字：{{count}} ‧ 预计移除：{{seconds}}s / {{duration}}", "review.legendCut": "剪除 (cut)", "review.legendFiller": "赘字 (filler)", "review.legendClip": "片段候选 (clip)", "review.legendDisabled": "虚线 = 已停用", "detail.monitor": "运行监控", "detail.runFailed": "启动运行失败：{{message}}", "deliverables.duration": "时长：{{duration}}", "deliverables.start": "开始", "deliverables.title": "标题", "deliverables.downloadWav": "下载 WAV",
  "episodes.loadError": "无法加载剧集：{{message}}", "status.ffmpeg": "ffmpeg {{state}}", "status.models": "模型 {{count}}/2", "new.pathPlaceholder": "粘贴本机绝对路径，例如 C:\\audio\\part-01.wav",
  "status.done": "已完成", "status.needsReview": "待审核", "status.running": "运行中", "status.neverRun": "未运行", "status.failed": "失败", "status.invalid": "配置无效", "status.unknown": "未知",
  "new.step": "步骤", "new.title": "标题 TITLE", "new.episode": "集数 EPISODE", "new.artist": "艺术家 ARTIST", "new.album": "专辑 ALBUM", "new.year": "年份 YEAR", "new.comment": "备注 COMMENT", "new.partsHeading": "段落音频", "new.assetsHeading": "配乐与章节", "new.totalDuration": "总时长 {{duration}}", "new.chapterHeading": "章节 CHAPTERS", "new.chapterTime": "mm:ss", "new.gain": "GAIN dB", "new.threshold": "THRESHOLD", "new.ratio": "RATIO", "new.attack": "ATTACK ms", "new.release": "RELEASE ms", "new.validationRequired": "请输入标题并至少添加一个段落音频文件", "new.chapterTimeError": "章节时间格式错误：{{time}}", "new.chapterExceedsDuration": "章节「{{title}}」超过音频总时长",
};

export default zhCN;
