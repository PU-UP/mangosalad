---
name: mangosalad-pages
description: 管理 mangosalad 网页和本人整页任务收件箱。用于接单、查询用户交给自己的任务、续接飞书中的网页任务讨论，以及创建和修改清单、可视化页面。
---

# mangosalad 页面

技能版本：{{VERSION}}。本安装身份：**{{AGENT}}**。所有操作只用此身份；不读取另一位的凭据，不代领另一位的任务。

## 加物品：直接执行，拿到回执再回复

用户让你给已有清单加东西时，必须使用下面的追加命令，不要生成整份替换 JSON，不要把读取或写临时文件当作已经提交。首次使用或用户反馈没更新时，重新读取本技能，不沿用会话里的旧示例。

```sh
python3 /home/ubuntu/mangosalad-desk/mango.py --agent {{AGENT}} append-items PAGE_ID --item "充电宝" --item "耳机"
```

不知道 PAGE_ID 时先 list 找到用户所指页面；无法确定则询问。命令会保留已有条目和勾选，跳过同名物品，处理版本冲突，并回读核验。失败时退出码非零，不得回复已完成。

只有本次真实工具返回 `verified:true` 才能说新增完成；按回执中的 added、already_present、total 和 url 回答，不心算数量，不伪造回执。不因用户回答一个澄清问题就跳过执行；涉及删除的疑问也不应阻塞已经明确授权的追加。不删除或替换其他人的条目。

其他创建/修改操作同样要实际写入并回读；没有成功工具结果，只能说明尚未完成。此规则适用于飞书聊天和网页任务。

## 日常操作与维护边界

日常清单、可视化、任务和提醒全部通过 mango.py / API 写入数据库。可视化 HTML 也是页面数据，不改 static/。草稿放 /tmp 或本人工作区，不放源码目录。

除非 waterman 明确要求维护网站程序，不修改源码、Git、服务配置、技能或文件权限，不提交、不部署，不使用 sudo 绕过只读代码保护。维护时先读源码仓库 AGENTS.md、VERSION 和线上 VERSION，按版本流程操作；不要把自己的旧会话状态当作当前版本。

产品名称：mangosalad 桌面（网页标题：mangosalad · 你的桌面）。接入技能名称：mangosalad-pages。

## 整份任务安排（2026-09-23 更新）

网页顶部「把这份任务交给」是整页安排，只有一个负责人、一个联系/开始时间、确定和取消。旧逐项提醒已停用。到时调度器启动你本人的工作会话，给出确认时快照和用户要求；无需用户另外发飞书消息。

时间的含义按内容决定：提醒类到时提醒用户核对/完成；讨论类到时主动开启讨论；工作类到时开始工作。不填时间则确认后尽快处理。普通页面编辑和勾选不等于提交任务。

接到调度器的整页任务，第一步必须调用 `python3 /home/ubuntu/mangosalad-desk/mango.py --agent {{AGENT}} task-ack TASK_ID`；回执成功才处理，失败/取消则停止。只有此回执使网页显示“Agent 已接单”。最终按调度器要求返回 JSON，调度器保存结果并从你的飞书身份发送，你不要再发一份。不要建立重复 cron。

用户问“我交给你什么任务/这个任务怎么样了”或回复标有「网页任务」的飞书消息时，先用 `python3 /home/ubuntu/mangosalad-desk/mango.py --agent {{AGENT}} my-tasks` 查看本人任务，再用 `task-get TASK_ID` 读取具体确认快照、要求、结果和状态，按用户回复继续讨论。另一位的任务不属于自己的收件箱。不要说自己没有见过任务，也不要仅靠长期记忆猜测。任务是持久记录，不自动写入人格记忆。

取消排队任务后不再启动；处理中取消会请求停止工作进程，已经发生的操作不能撤回。收起或删除整页也取消安排。页面修改不会偷偷扩大已确认任务的授权范围。后续需要改变负责者、时间、要求时，在网页取消当前安排，再重新确认。

网页按用户要求免密码且公开读写，提交任务仍需要已启用的设备，防止访客调用 Agent。此前的设备启用继续有效。用户要求启用时执行 `python3 /home/ubuntu/mangosalad-desk/mango.py --agent {{AGENT}} reminder-link`（兼容命令名称），只将返回的一次性链接发到已确认的 waterman 私聊，不放入公开页面。生成新链接替换尚未使用的旧链接，24 小时内一次有效。不要主动反复发链接。

当前网站服务是 mangosalad-desk，整页调度服务为 mangosalad-tasks.service。旧 mangosalad-reminders.timer 已停用。对用户和任务收件箱只使用三个状态：waiting（待处理）、done（已完成）、cancelled（已取消）。排队、执行和故障细节由系统管理，不增加用户状态。服务重启时中断的工作不会自动重跑，避免重复操作。提醒或讨论任务的目标是本次联系：成功发送后就是 done，不能显示“等待你回复”。这不代表现实任务已完成或话题已经聊完。用户在飞书回复时，读取本人 task-get 的要求和结果继续响应，不另建定时任务，不承诺系统会追踪回复。工作没完成或消息未确认送达仍是 waiting；错误必须说明，不可伪报 done。取消为 cancelled，不再执行。

## 使用

使用本机客户端 `/home/ubuntu/mangosalad-desk/mango.py`；`--agent` 使用你自己的名字（lychee 或 olive），不要输出或读取 token 文件。

```sh
python3 /home/ubuntu/mangosalad-desk/mango.py --agent {{AGENT}} list
python3 /home/ubuntu/mangosalad-desk/mango.py --agent {{AGENT}} get PAGE_ID
python3 /home/ubuntu/mangosalad-desk/mango.py --agent {{AGENT}} create --file /tmp/page.json
python3 /home/ubuntu/mangosalad-desk/mango.py --agent {{AGENT}} update PAGE_ID --file /tmp/change.json
```

JSON 使用 UTF-8。已有页面先 get，修改时传返回的 `revision`。409 表示别人刚改过，重新读取并合并用户这次需要的变化，不拿旧状态整页覆盖；不要丢失用户在网页上的勾选。调用成功后再次 get 核对，再回标题和网页链接。不把“已经生成代码”说成“已发布”。

创建清单：
```json
{"title":"明天购物","kind":"checklist","pinned":false,"state":{"items":[{"id":"milk","text":"牛奶","done":false}]}}
```

更新示例：`{"revision":3,"state":{"items":[...]}}`。只提供要改的字段；更新 state 时保留其中仍然有效的数据。项目 id 保持稳定。长期待办可以 `pinned:true`，临时清单不必固定。`archived:true` 表示“用完了/收起”，可恢复。不要根据日期擅自永久删除；用户明确要求删除时，delete 使用 `{"revision":3}`。

## 自定义可视化

创建 `kind:"canvas"`，`content:{"html":"..."}`，`state:{...}`。HTML 可以包含内联 CSS 和 JS，适合比较、图表、可调整的小工具；页面在隔离框架里运行，不支持外部脚本、网络请求、表单跳转或读取主站。图片需使用 data URL，不要把凭据放入页面。资料检索由你先完成，再把必要数据写入页面。

需要保存交互状态时，使用下面的消息协议。先收到 init 再绘制界面；保存成功才显示已保存；出错时保留用户输入、读取返回的最新状态并提示，不默默覆盖。

```js
let state = {}, revision;
window.addEventListener('message', e => {
  if (e.source !== parent) return;
  if (e.data.type === 'mango:init' || e.data.type === 'mango:saved') {
    state = e.data.state; revision = e.data.revision;
    // draw(state)
  }
  if (e.data.type === 'mango:error') {
    // Show e.data.error; latest state/revision are included for reconciliation.
  }
});
parent.postMessage({type:'mango:ready'}, '*');
// After a user edit, wait for mango:saved before sending another save:
// parent.postMessage({type:'mango:save', state:nextState, revision}, '*');
```

手机优先：文字清楚、控件易点、不要横向溢出。页面标题表达具体用途。复用这套发布入口即可，不需要为每个页面改 Nginx、安装依赖或重启网站。

## 桌面关注与排序

页面新增可选字段 `focus_date`（YYYY-MM-DD 或 null）。这是桌面关注日期，不是 Agent 执行时间，不自动发通知。用户明确指定日期才设置；不依据创建时间或标题擅自推断。近期关注按北京时间仅显示 focus_date <= 今天且未收起的页面；到日期当天开始持续显示，直到任务结束（收起）或删除，不提前展示未来日期；未填日期的页面在全部中显示。更改仍使用带 revision 的 update。桌面拖动顺序独立于页面内容，日常更新不要改桌面排序。

调度器要求 JSON 时，输出 kind（reminder/discussion/work）、status（done/waiting）和 message。提醒或开启讨论用 done；工作只有交付并核验后用 done，缺资料用 waiting。系统收到飞书回执才对用户显示 done。旧历史中的“已联系等待回复”按同样规则解释为本次联系已完成，不推断用户有没有回复。
