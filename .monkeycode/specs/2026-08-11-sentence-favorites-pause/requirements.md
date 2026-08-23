# Requirements Document

## Introduction

针对雅思考点词歌词播放器（yasi-rdtli/tli/player.html）的增强功能。用户练习听力时存在两种诉求：一是部分句子需要重复播放且句间需要留出停顿时间以便跟读；二是遇到没听懂的句子希望收藏起来，随时查看，并把这些收藏句子组成一个独立的播放序列反复精听。

## Glossary

- **播放器**: 雅思考点词歌词播放器页面 player.html
- **句子**: 词条中的一个播放单元（每句一句歌，SONGS 中的一项），有唯一 id
- **句间暂停**: 一个句子播放结束后到下一句开始之间的等待时长
- **收藏句**: 用户主动收藏的句子
- **收藏序列**: 按收藏时间顺序排列的收藏句构成的播放列表
- **播放模式**: order 顺序 / single 单曲循环 / random 随机，三选一

## Requirements

### Requirement 1: 句间暂停时长可配置

**User Story:** AS 听力练习者, I want 自定义每个句子播放后的暂停时长, so that 我可以留出跟读或复听的时间。

#### Acceptance Criteria

1. WHEN 用户在设置面板调整句间暂停时长，播放器 SHALL 将设置值持久化到 localStorage
2. WHEN 句子播放结束且当前播放模式为 order 或 random，播放器 SHALL 在等待用户设定的暂停时长后再开始下一句
3. WHEN 句间暂停处于倒计时中，播放器 SHALL 在界面显示"下一句 N 秒后播放"的提示，并允许用户点击跳过
4. WHEN 当前播放模式为 single 单曲循环，播放器 SHALL 立即重播当前句（不插入句间暂停）
5. WHEN 句间暂停时长为 0，播放器 SHALL 无缝立即播放下一句

### Requirement 2: 收藏按钮与收藏/取消收藏

**User Story:** AS 听力练习者, I want 一键收藏没听懂的句子, so that 之后可以集中复习。

#### Acceptance Criteria

1. WHEN 播放器处于播放状态，播放条 SHALL 展示一个收藏按钮，其选中状态反映当前句是否已收藏
2. WHEN 用户点击收藏按钮且当前句未收藏，播放器 SHALL 将当前句加入收藏并持久化
3. WHEN 用户点击收藏按钮且当前句已收藏，播放器 SHALL 从收藏中移除当前句并持久化
4. WHEN 播放器成功收藏或取消收藏，播放器 SHALL 给出短暂的操作反馈提示
5. WHEN 页面加载，播放器 SHALL 从 localStorage 恢复收藏数据

### Requirement 3: 收藏列表查看

**User Story:** AS 听力练习者, I want 查看所有已收藏的句子, so that 我可以快速定位并复习。

#### Acceptance Criteria

1. WHEN 用户打开歌单侧栏，播放器 SHALL 提供"全部句子 / 收藏夹"视图切换入口
2. WHEN 用户切换到收藏夹视图，播放器 SHALL 按收藏时间倒序展示收藏句（含句子文本、考点词与收藏时间）
3. WHEN 用户点击某个收藏句，播放器 SHALL 播放该句并保持收藏夹视图
4. WHEN 收藏夹为空，播放器 SHALL 显示空态提示

### Requirement 4: 收藏序列播放

**User Story:** AS 听力练习者, I want 把收藏句子组成一个播放序列, so that 我可以反复精听所有没听懂的句子。

#### Acceptance Criteria

1. WHEN 用户在收藏夹视图点击播放入口，播放器 SHALL 以收藏句按收藏顺序构成播放序列并开始播放
2. WHEN 收藏序列播放到最后一个句子，播放器 SHALL 从头开始循环播放
3. WHEN 收藏序列播放，播放器 SHALL 应用与普通播放一致的句间暂停时长
4. WHEN 用户在收藏序列播放过程中新增或取消收藏，播放器 SHALL 使当前序列在下一句切换时反映该变化
5. WHEN 收藏序列为空，播放器 SHALL 禁用播放入口并提示先收藏句子
