# Code Wiki — 技术实现文档 v1.0

> 基于 [REQUIREMENTS.md](./REQUIREMENTS.md) v3，本文档面向开发人员，描述各模块的技术实现细节、组件树、数据流和关键代码路径。

---

## 目录

1. [前端实现](#1-前端实现)
   - 1.0 [shadcn/ui 组件映射](#10-shadcnui-组件映射)
   - 1.1 [组件树](#11-组件树)
   - 1.2 [路由 & Tab 切换](#12-路由--tab-切换)
   - 1.3 [状态管理 (Zustand)](#13-状态管理-zustand)
   - 1.4 [主题系统](#14-主题系统)
   - 1.5 [关键组件实现](#15-关键组件实现)
2. [后端实现](#2-后端实现)
   - 2.1 [Pipeline 编排](#21-pipeline-编排)
   - 2.2 [Scanner 服务](#22-scanner-服务)
   - 2.3 [Analyzer 服务](#23-analyzer-服务)
   - 2.4 [Wiki Generator 服务](#24-wiki-generator-服务)
   - 2.5 [Chat & RAG 服务](#25-chat--rag-服务)
3. [Tauri Shell 层](#3-tauri-shell-层)
4. [数据模型](#4-数据模型)
5. [SSE 事件流](#5-sse-事件流)
6. [错误处理策略](#6-错误处理策略)

---

## 1. 前端实现

### 1.0 shadcn/ui 组件映射

基于 [shadcn/ui](https://ui.shadcn.com/)（Radix UI + TailwindCSS），将需求中的 UI 元素映射到具体组件：

| 页面元素 | shadcn/ui 组件 | 用途 |
|----------|---------------|------|
| 左侧 Tab 导航 | `Button` (variant="ghost") + 自定 active 样式 | 垂直三个 Tab 按钮 |
| 文件树右键菜单 | `DropdownMenu` | 右键弹出「分析/排除/取消排除」 |
| 设置页输入框 | `Input` | 仓库路径、API Base URL 等 |
| 密码输入框 | `Input` (type="password") | API Key 输入 |
| 多行文本输入 | `Textarea` | 排除规则编辑 |
| 下拉选择 | `Select` (含 SelectTrigger/Content/Item) | LLM 模型选择 |
| 滑块 | `Slider` | Temperature 调节 |
| 主题单选 | `RadioGroup` + `RadioGroupItem` | 亮色/暗色/跟随系统 |
| 按钮 | `Button` (variant: default/outline/destructive) | 开始分析、取消、测试连接等 |
| 进度条 | `Progress` | 分析进度展示 |
| Chat 抽屉 | `Sheet` | 右侧滑出对话面板 |
| 全局通知 | `sonner` (toast) | 操作成功/失败提示 |
| 对话框 | `Dialog` | 确认对话框（如清除 Wiki 确认） |
| 工具提示 | `Tooltip` | 图标按钮 hover 说明 |
| 标签切换 | `Tabs` | Wiki 图表切换（架构图/类图/时序图） |
| 滚动区域 | `ScrollArea` | 文件树、Wiki 内容、Chat 消息列表 |
| 折叠面板 | `Collapsible` / `Accordion` | 设置页各配置区域折叠 |
| 徽标 | `Badge` | 文件分析状态标签 |
| 骨架屏 | `Skeleton` | 加载中占位 |

初始化命令：

```bash
npx shadcn@latest init          # 一次配置，生成 components.json
npx shadcn@latest add button dropdown-menu input textarea select slider
npx shadcn@latest add radio-group progress sheet dialog tooltip
npx shadcn@latest add tabs scroll-area accordion badge skeleton
npx shadcn@latest add sonner    # toast 通知
```

### 1.1 组件树

```
<App>
├── <ThemeProvider>                              // 主题上下文
│   ├── <AppShell>                               // 三栏布局容器
│   │   ├── <TopBar>                             // 顶栏
│   │   │   ├── Logo + 标题
│   │   │   ├── <ThemeToggleButton />            // 快捷主题切换
│   │   │   └── <AnalysisStatusIndicator />      // 分析状态指示器
│   │   │
│   │   ├── <LeftNav>                            // 左侧垂直 Tab
│   │   │   ├── <NavTab icon="code"  label="Code"  active={...} />
│   │   │   ├── <NavTab icon="wiki"  label="Wiki"  active={...} />
│   │   │   └── <NavTab icon="settings" label="设置" active={...} />
│   │   │
│   │   ├── <MainContent>                        // 主内容区（根据 activeTab 渲染）
│   │   │   ├── {activeTab === 'code'     && <CodePanel />}
│   │   │   ├── {activeTab === 'wiki'     && <WikiPanel />}
│   │   │   └── {activeTab === 'settings' && <SettingsPanel />}
│   │   │
│   │   ├── <ChatDrawer>                         // 右侧抽屉（始终可呼出）
│   │   │   ├── <ChatMessageList />
│   │   │   │   └── <ChatMessage /> (×N)
│   │   │   └── <ChatInput />
│   │   │
│   │   └── <StatusBar />                        // 底栏状态条
│   │
│   └── <ToastContainer />                       // 全局通知
```

#### CodePanel 展开

```
<CodePanel>
├── <SearchBar />                                // 文件名模糊搜索
└── <FileTree>                                   // 仓库文件树
    └── <FileTreeNode> (×N, 递归)
        ├── 状态图标 (✅/⏳/🔄)
        ├── 文件名 (被排除时灰显+删除线)
        └── <ContextMenu>                        // 右键菜单
            ├── "分析此文件"
            ├── "排除此文件"
            └── "取消排除"
```

#### WikiPanel 展开

```
<WikiPanel>
├── <WikiTree />                                 // Wiki 文件树（镜像源码结构）
└── <WikiContent>                                // 当前选中 Wiki 页面
    ├── <WikiPage>                               // Markdown 渲染
    │   └── <SourceLink /> (×N)                  // [@src:path:line] → 可点击
    └── <DiagramViewer>                          // Mermaid 图表
        ├── Tab: 架构图
        ├── Tab: 类图
        └── Tab: 时序图
```

#### SettingsPanel 展开

```
<SettingsPanel>
├── <RepoConfig>                                 // 区域一
│   ├── 仓库路径输入 + 浏览按钮
│   ├── 排除规则多行输入
│   └── 当前状态只读展示
├── <LLMConfig>                                  // 区域二
│   ├── API Key 密码输入
│   ├── 模型下拉选择
│   ├── Base URL 输入
│   ├── Temperature 滑块
│   └── "测试连接" 按钮
├── <ThemeSwitch>                                // 区域三
│   ├── ○ 亮色
│   ├── ○ 暗色
│   └── ○ 跟随系统
├── <AnalysisControl>                            // 区域四
│   ├── 分析模式选择 (全部/部分)
│   ├── 文件选择器 (部分模式)
│   ├── 进度条 + 状态文字
│   └── "开始分析" / "取消" 按钮
└── <AboutSection />                             // 区域五
```

---

### 1.2 路由 & Tab 切换

MVP 阶段**不使用 React Router**，左侧 Tab 切换通过 Zustand `activeTab` 状态控制条件渲染。

```typescript
// store/configStore.ts (片段)
interface AppState {
  activeTab: 'code' | 'wiki' | 'settings';
  chatOpen: boolean;
  theme: 'light' | 'dark' | 'system';
  // ...
  setActiveTab: (tab: AppState['activeTab']) => void;
  toggleChat: () => void;
}
```

Tab 切换逻辑：

```tsx
// components/layout/AppShell.tsx (片段)
const activeTab = useConfigStore(s => s.activeTab);

<main className="flex-1 overflow-hidden">
  {activeTab === 'code'     && <CodePanel />}
  {activeTab === 'wiki'     && <WikiPanel />}
  {activeTab === 'settings' && <SettingsPanel />}
</main>
```

---

### 1.3 状态管理 (Zustand)

使用单一 Zustand store 管理全局状态，避免 prop drilling。

```typescript
// store/configStore.ts
import { create } from 'zustand';

interface ConfigState {
  // --- Tab 状态 ---
  activeTab: 'code' | 'wiki' | 'settings';
  setActiveTab: (tab: ConfigState['activeTab']) => void;

  // --- 主题 ---
  theme: 'light' | 'dark' | 'system';
  setTheme: (t: ConfigState['theme']) => void;

  // --- Chat 抽屉 ---
  chatOpen: boolean;
  toggleChat: () => void;

  // --- 配置（同步自后端） ---
  repoPath: string;
  excludePatterns: string[];
  llmModel: string;
  llmBaseUrl: string;
  llmTemperature: number;
  // API Key 仅通过 Tauri Store 读写，不进入 Zustand

  // --- 分析状态（SSE 驱动） ---
  analysisStatus: 'idle' | 'scanning' | 'analyzing' | 'generating' | 'done' | 'error';
  analysisProgress: number;       // 0-100
  analysisCurrentStep: string;
  lastAnalysisTime: string | null;

  // --- Wiki 树 ---
  wikiTree: WikiTreeNode[];

  // --- 文件树 ---
  fileTree: FileTreeNode[];

  // --- Actions ---
  fetchConfig: () => Promise<void>;
  saveConfig: (partial: Partial<ConfigState>) => Promise<void>;
  triggerScan: (mode: 'full' | 'partial', files?: string[]) => Promise<void>;
  fetchWikiTree: () => Promise<void>;
  fetchFileTree: () => Promise<void>;
}
```

---

### 1.4 主题系统

使用 TailwindCSS `dark:` 类 + CSS 自定义属性实现，切换即时生效无需刷新。

```css
/* styles/globals.css */
:root {
  --color-bg-primary:    #ffffff;
  --color-bg-secondary:  #f3f4f6;
  --color-text-primary:  #111827;
  --color-text-secondary:#6b7280;
  --color-border:        #e5e7eb;
  --color-accent:        #2563eb;
}

.dark {
  --color-bg-primary:    #1f2937;
  --color-bg-secondary:  #111827;
  --color-text-primary:  #f9fafb;
  --color-text-secondary:#9ca3af;
  --color-border:        #374151;
  --color-accent:        #3b82f6;
}
```

```typescript
// hooks/useTheme.ts
import { useEffect } from 'react';
import { useConfigStore } from '../store/configStore';

export function useTheme() {
  const theme = useConfigStore(s => s.theme);

  useEffect(() => {
    const root = document.documentElement;

    if (theme === 'system') {
      const mq = window.matchMedia('(prefers-color-scheme: dark)');
      const apply = () => root.classList.toggle('dark', mq.matches);
      apply();
      mq.addEventListener('change', apply);
      return () => mq.removeEventListener('change', apply);
    }

    root.classList.toggle('dark', theme === 'dark');
  }, [theme]);
}
```

---

### 1.5 关键组件实现

#### 1.5.1 LeftNav — 垂直 Tab 导航（shadcn Button）

```tsx
// components/layout/LeftNav.tsx
import { Button } from '@/components/ui/button';
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip';
import { CodeIcon, BookOpenIcon, SettingsIcon } from 'lucide-react';
import { cn } from '@/lib/utils';
import { useConfigStore } from '@/store/configStore';

const tabs = [
  { id: 'code' as const,     label: 'Code',     icon: CodeIcon },
  { id: 'wiki' as const,     label: 'Wiki',     icon: BookOpenIcon },
  { id: 'settings' as const, label: '设置',      icon: SettingsIcon },
];

export function LeftNav() {
  const activeTab = useConfigStore(s => s.activeTab);
  const setActiveTab = useConfigStore(s => s.setActiveTab);

  return (
    <nav className="w-16 flex flex-col items-center py-4 gap-1
                    bg-secondary border-r border-border">
      {tabs.map(tab => (
        <Tooltip key={tab.id}>
          <TooltipTrigger asChild>
            <Button
              variant="ghost"
              size="icon"
              onClick={() => setActiveTab(tab.id)}
              className={cn(
                'flex flex-col items-center gap-0.5 h-auto w-14 py-2',
                'text-[10px] font-normal rounded-lg transition-colors',
                activeTab === tab.id
                  ? 'bg-accent text-accent-foreground hover:bg-accent/90'
                  : 'text-muted-foreground hover:bg-accent/50 hover:text-foreground'
              )}
            >
              <tab.icon size={20} />
              <span>{tab.label}</span>
            </Button>
          </TooltipTrigger>
          <TooltipContent side="right">{tab.label}</TooltipContent>
        </Tooltip>
      ))}
    </nav>
  );
}
```

#### TopBar — 顶栏（shadcn Button + Tooltip）

```tsx
// components/layout/TopBar.tsx
import { Button } from '@/components/ui/button';
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip';
import { Badge } from '@/components/ui/badge';
import { SunIcon, MoonIcon, MessageCircleIcon } from 'lucide-react';
import { useConfigStore } from '@/store/configStore';

export function TopBar() {
  const theme = useConfigStore(s => s.theme);
  const setTheme = useConfigStore(s => s.setTheme);
  const toggleChat = useConfigStore(s => s.toggleChat);
  const analysisStatus = useConfigStore(s => s.analysisStatus);
  const setActiveTab = useConfigStore(s => s.setActiveTab);

  return (
    <header className="h-12 border-b border-border flex items-center justify-between px-4
                       bg-background shrink-0">
      <div className="flex items-center gap-3">
        <h1 className="font-semibold text-sm tracking-tight">Code Wiki</h1>
        {analysisStatus !== 'idle' && analysisStatus !== 'done' && (
          <Badge variant="secondary" className="text-[10px]">
            {analysisStatus === 'scanning' && '🔍 扫描中'}
            {analysisStatus === 'analyzing' && '⚙ 分析中'}
            {analysisStatus === 'generating' && '📝 生成中'}
          </Badge>
        )}
      </div>

      <div className="flex items-center gap-1">
        {/* 主题切换 */}
        <Tooltip>
          <TooltipTrigger asChild>
            <Button variant="ghost" size="icon" onClick={() =>
              setTheme(theme === 'dark' ? 'light' : 'dark')
            }>
              {theme === 'dark' ? <SunIcon size={18} /> : <MoonIcon size={18} />}
            </Button>
          </TooltipTrigger>
          <TooltipContent>切换主题</TooltipContent>
        </Tooltip>

        {/* Chat 抽屉开关 */}
        <Tooltip>
          <TooltipTrigger asChild>
            <Button variant="ghost" size="icon" onClick={toggleChat}>
              <MessageCircleIcon size={18} />
            </Button>
          </TooltipTrigger>
          <TooltipContent>AI 问答</TooltipContent>
        </Tooltip>

        {/* 设置入口 */}
        <Tooltip>
          <TooltipTrigger asChild>
            <Button variant="ghost" size="icon" onClick={() => setActiveTab('settings')}>
              <SettingsIcon size={18} />
            </Button>
          </TooltipTrigger>
          <TooltipContent>设置</TooltipContent>
        </Tooltip>
      </div>
    </header>
  );
}
```

#### StatusBar — 底栏状态条

#### 1.5.2 FileTree — 文件树 + 右键菜单（shadcn DropdownMenu）

```tsx
// components/code/FileTree.tsx
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
} from '@/components/ui/dropdown-menu';
import { Input } from '@/components/ui/input';
import { ScrollArea } from '@/components/ui/scroll-area';
import { Badge } from '@/components/ui/badge';

interface FileTreeNode {
  name: string;
  path: string;
  type: 'file' | 'directory';
  status: 'analyzed' | 'pending' | 'analyzing';
  excluded: boolean;
  children?: FileTreeNode[];
}

export function FileTree() {
  const fileTree = useConfigStore(s => s.fileTree);
  const [contextMenu, setContextMenu] = useState<{
    x: number; y: number; node: FileTreeNode;
  } | null>(null);
  const [search, setSearch] = useState('');

  const handleContextMenu = (e: React.MouseEvent, node: FileTreeNode) => {
    e.preventDefault();
    setContextMenu({ x: e.clientX, y: e.clientY, node });
  };

  return (
    <div className="flex flex-col h-full">
      {/* 搜索框 */}
      <div className="p-2">
        <Input
          placeholder="搜索文件..."
          value={search}
          onChange={e => setSearch(e.target.value)}
          className="h-8 text-sm"
        />
      </div>

      {/* 文件树 */}
      <ScrollArea className="flex-1">
        {fileTree.map(node => (
          <FileTreeNodeComponent
            key={node.path}
            node={node}
            onContextMenu={handleContextMenu}
          />
        ))}
      </ScrollArea>

      {/* 右键菜单 */}
      {contextMenu && (
        <DropdownMenu
          open={!!contextMenu}
          onOpenChange={() => setContextMenu(null)}
        >
          <DropdownMenuContent
            className="absolute"
            style={{ left: contextMenu.x, top: contextMenu.y }}
          >
            <DropdownMenuItem onClick={() => analyzeSelected([contextMenu.node.path])}>
              📊 分析此文件
            </DropdownMenuItem>
            <DropdownMenuSeparator />
            {contextMenu.node.excluded ? (
              <DropdownMenuItem onClick={() => unexcludeFile(contextMenu.node.path)}>
                🔓 取消排除
              </DropdownMenuItem>
            ) : (
              <DropdownMenuItem onClick={() => excludeFile(contextMenu.node.path)}>
                🚫 排除此文件
              </DropdownMenuItem>
            )}
          </DropdownMenuContent>
        </DropdownMenu>
      )}
    </div>
  );
}

// 文件树节点组件
function FileTreeNodeComponent({ node, onContextMenu, depth = 0 }: {
  node: FileTreeNode;
  onContextMenu: (e: React.MouseEvent, n: FileTreeNode) => void;
  depth?: number;
}) {
  const statusIcon = {
    analyzed:  '✅',
    pending:   '⏳',
    analyzing: '🔄',
  }[node.status];

  return (
    <>
      <div
        className={cn(
          'flex items-center gap-2 px-2 py-1 cursor-pointer hover:bg-accent/30 text-sm',
          node.excluded && 'opacity-40 line-through',
        )}
        style={{ paddingLeft: `${depth * 16 + 8}px` }}
        onContextMenu={e => onContextMenu(e, node)}
      >
        <span className="text-xs w-4">{statusIcon}</span>
        <span className="truncate">{node.name}</span>
        {node.excluded && (
          <Badge variant="outline" className="ml-auto text-[10px] h-4">已排除</Badge>
        )}
      </div>
      {node.children?.map(child => (
        <FileTreeNodeComponent
          key={child.path}
          node={child}
          onContextMenu={onContextMenu}
          depth={depth + 1}
        />
      ))}
    </>
  );
}
```

#### 1.5.3 WikiPage — Markdown 渲染 + 源码链接

```tsx
// components/wiki/WikiPage.tsx
import ReactMarkdown from 'react-markdown';
import { SourceLink } from './SourceLink';

// 自定义渲染器：把 [@src:path:line] 转为可点击链接
function customRenderer() {
  return {
    text({ value }: { value: string }) {
      // 匹配 [@src:relative/path:line]
      const parts = value.split(/(\[@src:[^\]]+\])/g);
      return parts.map((part, i) => {
        const match = part.match(/^\[@src:(.+):(\d+)\]$/);
        if (match) {
          return <SourceLink key={i} file={match[1]} line={Number(match[2])} />;
        }
        return <span key={i}>{part}</span>;
      });
    },
  };
}

export function WikiPage({ content }: { content: string }) {
  return (
    <article className="prose dark:prose-invert max-w-none p-6">
      <ReactMarkdown components={customRenderer()}>
        {content}
      </ReactMarkdown>
    </article>
  );
}
```

#### 1.5.4 SettingsPanel — 设置主面板（shadcn Accordion 折叠面板）

```tsx
// components/settings/SettingsPanel.tsx
import { ScrollArea } from '@/components/ui/scroll-area';
import {
  Accordion,
  AccordionContent,
  AccordionItem,
  AccordionTrigger,
} from '@/components/ui/accordion';
import { RepoConfig } from './RepoConfig';
import { LLMConfig } from './LLMConfig';
import { ThemeSwitch } from './ThemeSwitch';
import { AnalysisControl } from './AnalysisControl';

export function SettingsPanel() {
  return (
    <ScrollArea className="h-full">
      <div className="max-w-2xl mx-auto p-6 space-y-6">
        <h2 className="text-xl font-semibold">设置</h2>

        <Accordion type="multiple" defaultValue={['repo', 'llm', 'theme', 'analysis']}>
          <AccordionItem value="repo">
            <AccordionTrigger>📁 仓库配置</AccordionTrigger>
            <AccordionContent><RepoConfig /></AccordionContent>
          </AccordionItem>

          <AccordionItem value="llm">
            <AccordionTrigger>🤖 LLM 配置</AccordionTrigger>
            <AccordionContent><LLMConfig /></AccordionContent>
          </AccordionItem>

          <AccordionItem value="theme">
            <AccordionTrigger>🎨 主题切换</AccordionTrigger>
            <AccordionContent><ThemeSwitch /></AccordionContent>
          </AccordionItem>

          <AccordionItem value="analysis">
            <AccordionTrigger>⚡ 分析设置</AccordionTrigger>
            <AccordionContent><AnalysisControl /></AccordionContent>
          </AccordionItem>
        </Accordion>
      </div>
    </ScrollArea>
  );
}
```

#### RepoConfig — 仓库路径 + 排除规则（shadcn Input + Textarea + Button）

```tsx
// components/settings/RepoConfig.tsx
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import { Button } from '@/components/ui/button';
import { FolderOpenIcon } from 'lucide-react';
import { useConfigStore } from '@/store/configStore';
import { invoke } from '@tauri-apps/api/core';

export function RepoConfig() {
  const repoPath = useConfigStore(s => s.repoPath);
  const excludePatterns = useConfigStore(s => s.excludePatterns);
  const setRepoPath = useConfigStore(s => s.setRepoPath);
  const setExcludePatterns = useConfigStore(s => s.setExcludePatterns);

  return (
    <div className="space-y-4 pt-2">
      <div className="space-y-1.5">
        <label className="text-sm font-medium">仓库路径</label>
        <div className="flex gap-2">
          <Input value={repoPath} readOnly placeholder="选择本地仓库目录..." />
          <Button variant="outline" size="icon" onClick={async () => {
            const path = await invoke<string>('pick_repository');
            if (path) setRepoPath(path);
          }}>
            <FolderOpenIcon size={16} />
          </Button>
        </div>
      </div>

      <div className="space-y-1.5">
        <label className="text-sm font-medium">排除规则（每行一个 glob 模式）</label>
        <Textarea
          value={excludePatterns.join('\n')}
          onChange={e => setExcludePatterns(e.target.value.split('\n').filter(Boolean))}
          placeholder="__pycache__/"
          rows={6}
          className="font-mono text-sm"
        />
        <p className="text-xs text-muted-foreground">
          * 匹配任意字符，** 匹配任意路径，? 匹配单个字符
        </p>
      </div>
    </div>
  );
}
```

#### LLMConfig — API Key + 模型 + 参数（shadcn Input + Select + Slider + Button）

```tsx
// components/settings/LLMConfig.tsx
import { useState } from 'react';
import { Input } from '@/components/ui/input';
import { Button } from '@/components/ui/button';
import { Slider } from '@/components/ui/slider';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { EyeIcon, EyeOffIcon } from 'lucide-react';
import { useConfigStore } from '@/store/configStore';
import { toast } from 'sonner';

export function LLMConfig() {
  const [showKey, setShowKey] = useState(false);
  const llm = useConfigStore(s => s.llm);
  const setLLM = useConfigStore(s => s.setLLM);
  const updateLLM = (patch: Partial<typeof llm>) => setLLM({ ...llm, ...patch });

  const testConnection = async () => {
    try {
      const res = await fetch(`${llm.baseUrl}/v1/models`, {
        headers: { Authorization: `Bearer ${llm.apiKey}` },
      });
      if (res.ok) toast.success('连接成功');
      else toast.error(`连接失败: ${res.status}`);
    } catch {
      toast.error('网络错误，请检查 Base URL');
    }
  };

  return (
    <div className="space-y-4 pt-2">
      <div className="space-y-1.5">
        <label className="text-sm font-medium">API Key</label>
        <div className="flex gap-2">
          <Input
            type={showKey ? 'text' : 'password'}
            value={llm.apiKey}
            onChange={e => updateLLM({ apiKey: e.target.value })}
            placeholder="sk-..."
          />
          <Button variant="outline" size="icon" onClick={() => setShowKey(!showKey)}>
            {showKey ? <EyeOffIcon size={16} /> : <EyeIcon size={16} />}
          </Button>
        </div>
      </div>

      <div className="space-y-1.5">
        <label className="text-sm font-medium">模型</label>
        <Select value={llm.model} onValueChange={v => updateLLM({ model: v as typeof llm.model })}>
          <SelectTrigger><SelectValue /></SelectTrigger>
          <SelectContent>
            <SelectItem value="deepseek-v4-flash">DeepSeek V4 Flash（快速 · 推荐）</SelectItem>
            <SelectItem value="deepseek-v4-pro">DeepSeek V4 Pro（高质量）</SelectItem>
          </SelectContent>
        </Select>
      </div>

      <div className="space-y-1.5">
        <label className="text-sm font-medium">API Base URL</label>
        <Input value={llm.baseUrl} onChange={e => updateLLM({ baseUrl: e.target.value })} />
      </div>

      <div className="space-y-1.5">
        <label className="text-sm font-medium">Temperature: {llm.temperature.toFixed(1)}</label>
        <Slider value={[llm.temperature]} onValueChange={([v]) => updateLLM({ temperature: v })}
                min={0} max={1} step={0.1} />
      </div>

      <Button variant="outline" size="sm" onClick={testConnection}>🔗 测试连接</Button>
    </div>
  );
}
```

#### ThemeSwitch — 亮色/暗色/跟随系统（shadcn RadioGroup）

```tsx
// components/settings/ThemeSwitch.tsx
import { RadioGroup, RadioGroupItem } from '@/components/ui/radio-group';
import { Label } from '@/components/ui/label';
import { SunIcon, MoonIcon, MonitorIcon } from 'lucide-react';
import { useConfigStore } from '@/store/configStore';

const themes = [
  { value: 'light' as const,  label: '亮色',     icon: SunIcon },
  { value: 'dark' as const,   label: '暗色',     icon: MoonIcon },
  { value: 'system' as const, label: '跟随系统',  icon: MonitorIcon },
];

export function ThemeSwitch() {
  const theme = useConfigStore(s => s.theme);
  const setTheme = useConfigStore(s => s.setTheme);

  return (
    <RadioGroup value={theme} onValueChange={setTheme} className="pt-2">
      {themes.map(({ value, label, icon: Icon }) => (
        <div key={value} className="flex items-center space-x-2 py-1">
          <RadioGroupItem value={value} id={`theme-${value}`} />
          <Label htmlFor={`theme-${value}`} className="flex items-center gap-2 cursor-pointer">
            <Icon size={16} /> {label}
          </Label>
        </div>
      ))}
    </RadioGroup>
  );
}
```

#### AnalysisControl — 分析模式 + 进度条 + 触发按钮（shadcn Progress + Button）

```tsx
// components/settings/AnalysisControl.tsx
import { useState } from 'react';
import { Button } from '@/components/ui/button';
import { Progress } from '@/components/ui/progress';
import { RadioGroup, RadioGroupItem } from '@/components/ui/radio-group';
import { Label } from '@/components/ui/label';
import { Badge } from '@/components/ui/badge';
import { useConfigStore } from '@/store/configStore';

export function AnalysisControl() {
  const [mode, setMode] = useState<'full' | 'partial'>('full');
  const analysisStatus = useConfigStore(s => s.analysisStatus);
  const analysisProgress = useConfigStore(s => s.analysisProgress);
  const triggerScan = useConfigStore(s => s.triggerScan);

  const isRunning = !['idle', 'done', 'error'].includes(analysisStatus);

  return (
    <div className="space-y-4 pt-2">
      <RadioGroup value={mode} onValueChange={v => setMode(v as 'full' | 'partial')}>
        <div className="flex items-center space-x-2">
          <RadioGroupItem value="full" id="mode-full" disabled={isRunning} />
          <Label htmlFor="mode-full">全部分析 — 分析整个仓库</Label>
        </div>
        <div className="flex items-center space-x-2">
          <RadioGroupItem value="partial" id="mode-partial" disabled={isRunning} />
          <Label htmlFor="mode-partial">部分分析 — 选择文件后分析</Label>
        </div>
      </RadioGroup>

      {isRunning && (
        <div className="space-y-2">
          <Progress value={analysisProgress} />
          <div className="flex items-center gap-2">
            <Badge variant="secondary">{analysisProgress}%</Badge>
            <span className="text-sm text-muted-foreground">
              {useConfigStore.getState().analysisCurrentStep}
            </span>
          </div>
        </div>
      )}

      <div className="flex gap-2">
        <Button onClick={() => triggerScan(mode)} disabled={isRunning}>
          ⚡ 开始分析
        </Button>
      </div>
    </div>
  );
}
```

#### 1.5.5 ChatDrawer — SSE 流式对话（shadcn Sheet）

```tsx
// components/chat/ChatDrawer.tsx
import { Sheet, SheetContent, SheetHeader, SheetTitle } from '@/components/ui/sheet';
import { ScrollArea } from '@/components/ui/scroll-area';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { SendIcon, BotIcon, UserIcon } from 'lucide-react';
import ReactMarkdown from 'react-markdown';
import { cn } from '@/lib/utils';
import { useConfigStore } from '@/store/configStore';
import { sourceLinkRenderer } from '@/wiki/SourceLink';

export function ChatDrawer() {
  const chatOpen = useConfigStore(s => s.chatOpen);
  const toggleChat = useConfigStore(s => s.toggleChat);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState('');
  const [streaming, setStreaming] = useState(false);

  const sendMessage = async () => {
    if (!input.trim() || streaming) return;
    const question = input.trim();
    setInput('');
    setMessages(prev => [...prev, { role: 'user', content: question }]);
    setStreaming(true);

    try {
      const response = await fetch('/api/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ question, history: messages.slice(-10) }),
      });

      const reader = response.body!.getReader();
      const decoder = new TextDecoder();
      let buffer = '';
      setMessages(prev => [...prev, { role: 'assistant', content: '' }]);

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n');
        buffer = lines.pop() || '';
        for (const line of lines) {
          if (line.startsWith('data: ')) {
            const chunk = line.slice(6);
            if (chunk === '[DONE]') { setStreaming(false); return; }
            setMessages(prev => {
              const updated = [...prev];
              updated[updated.length - 1] = {
                ...updated[updated.length - 1],
                content: updated[updated.length - 1].content + chunk,
              };
              return updated;
            });
          }
        }
      }
    } catch {
      setMessages(prev => [...prev, { role: 'assistant', content: '⚠️ 请求失败，请重试' }]);
    } finally {
      setStreaming(false);
    }
  };

  return (
    <Sheet open={chatOpen} onOpenChange={toggleChat}>
      <SheetContent side="right" className="w-96 p-0 flex flex-col">
        <SheetHeader className="px-4 py-3 border-b">
          <SheetTitle className="flex items-center gap-2 text-sm">
            <BotIcon size={18} /> Code Wiki Chat
          </SheetTitle>
        </SheetHeader>

        <ScrollArea className="flex-1 px-4 py-2">
          {messages.map((msg, i) => (
            <div key={i} className={cn(
              'flex gap-2 py-2',
              msg.role === 'user' ? 'justify-end' : 'justify-start'
            )}>
              {msg.role === 'assistant' && <BotIcon size={16} className="mt-1 shrink-0" />}
              <div className={cn(
                'rounded-lg px-3 py-2 text-sm max-w-[85%]',
                msg.role === 'user'
                  ? 'bg-primary text-primary-foreground'
                  : 'bg-muted'
              )}>
                <ReactMarkdown components={sourceLinkRenderer}>
                  {msg.content}
                </ReactMarkdown>
              </div>
              {msg.role === 'user' && <UserIcon size={16} className="mt-1 shrink-0" />}
            </div>
          ))}
          {streaming && messages[messages.length -1]?.role === 'assistant' && (
            <span className="inline-block w-2 h-4 bg-primary animate-pulse ml-1" />
          )}
        </ScrollArea>

        <div className="p-3 border-t flex gap-2">
          <Input
            value={input}
            onChange={e => setInput(e.target.value)}
            onKeyDown={e => e.key === 'Enter' && sendMessage()}
            placeholder="基于 Wiki 提问..."
            disabled={streaming}
          />
          <Button size="icon" onClick={sendMessage} disabled={streaming || !input.trim()}>
            <SendIcon size={16} />
          </Button>
        </div>
      </SheetContent>
    </Sheet>
  );
}
```

### 1.6 前端依赖

shadcn/ui 作为组件库，基于 Radix UI + TailwindCSS。

**核心依赖**：

| 包 | 用途 |
|----|------|
| `lucide-react` | 图标库（Code/Wiki/Settings/Sun/Moon 等） |
| `react-markdown` | Wiki 页面和 Chat 消息的 Markdown 渲染 |
| `mermaid` | 架构图/类图/时序图渲染 |
| `class-variance-authority` | shadcn/ui 依赖，变体管理 |
| `clsx` | 类名合并 |
| `tailwind-merge` | TailwindCSS 类名冲突解决 |
| `sonner` | Toast 通知 |
| `@tauri-apps/api` | Tauri 前端 API（文件对话框、编辑器调用） |

**shadcn/ui 组件清单**：button, input, textarea, select, slider, radio-group, progress, sheet, dropdown-menu, accordion, tooltip, scroll-area, badge, dialog, tabs, skeleton, sonner.

初始化命令：
```bash
npx shadcn@latest init
npx shadcn@latest add button input textarea select slider radio-group \
  progress sheet dropdown-menu accordion tooltip scroll-area \
  badge dialog tabs skeleton sonner
```

```typescript
// src/lib/utils.ts — shadcn/ui 必需工具函数
import { type ClassValue, clsx } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}
```

---

## 2. 后端实现

### 2.1 Pipeline 编排

`pipeline.py` 是后端的核心编排器，统一管理全量/增量/部分三种分析模式。

```python
# backend/pipeline.py
from enum import Enum
from dataclasses import dataclass
from typing import List, Optional
import asyncio

class PipelineMode(Enum):
    FULL = "full"           # 全量分析
    PARTIAL = "partial"     # 部分分析（指定文件）
    INCREMENTAL = "incremental"  # 增量分析（文件监听触发）

@dataclass
class PipelineContext:
    mode: PipelineMode
    repo_path: str
    target_files: Optional[List[str]] = None   # PARTIAL 模式下的目标文件
    changed_files: Optional[List[str]] = None  # INCREMENTAL 模式下的变更文件

class Pipeline:
    def __init__(self, scanner, analyzer, wiki_gen, embedder):
        self.scanner = scanner
        self.analyzer = analyzer
        self.wiki_gen = wiki_gen
        self.embedder = embedder

    async def run(self, ctx: PipelineContext, progress_callback):
        """
        统一入口，根据 mode 分发到不同执行路径。
        progress_callback(step: str, progress: float) 用于 SSE 推送进度。
        """
        if ctx.mode == PipelineMode.FULL:
            return await self._run_full(ctx, progress_callback)
        elif ctx.mode == PipelineMode.PARTIAL:
            return await self._run_partial(ctx, progress_callback)
        elif ctx.mode == PipelineMode.INCREMENTAL:
            return await self._run_incremental(ctx, progress_callback)

    async def _run_full(self, ctx, progress):
        """全量分析：扫描全部 → 全量生成 → 全量覆盖"""
        progress("scanning", 0.1)
        files = self.scanner.scan_all(ctx.repo_path)          # Step 1: 扫描

        progress("analyzing", 0.3)
        entities = self.analyzer.analyze_batch(files)         # Step 2: AST 分析
        dep_graph = self.analyzer.build_dependency_graph(entities)

        progress("generating", 0.6)
        wiki_pages = await self.wiki_gen.generate_all(        # Step 3: LLM 生成
            entities, dep_graph
        )

        progress("writing", 0.85)
        self.wiki_gen.write_all(ctx.repo_path, wiki_pages)    # Step 4: 写入 .code-wiki/

        progress("embedding", 0.95)
        self.embedder.rebuild_index(ctx.repo_path, wiki_pages)# Step 5: Chroma 重建索引

        progress("done", 1.0)

    async def _run_partial(self, ctx, progress):
        """部分分析：仅分析指定文件，局部覆盖对应 .md"""
        files = ctx.target_files
        progress("analyzing", 0.2)
        entities = self.analyzer.analyze_batch(files)

        progress("generating", 0.5)
        wiki_pages = await self.wiki_gen.generate_partial(entities)

        progress("writing", 0.8)
        self.wiki_gen.write_partial(ctx.repo_path, wiki_pages)  # 局部覆盖

        progress("embedding", 0.95)
        self.embedder.update_index(ctx.repo_path, wiki_pages)   # 增量更新 Chroma

        progress("done", 1.0)

    async def _run_incremental(self, ctx, progress):
        """增量分析：文件变更触发，自动分析受影响文件"""
        changed = ctx.changed_files
        affected = self.analyzer.find_affected_files(changed)     # 找到导入变更模块的文件
        all_targets = list(set(changed) | set(affected))

        progress("analyzing", 0.2)
        entities = self.analyzer.analyze_batch(all_targets)

        progress("generating", 0.5)
        wiki_pages = await self.wiki_gen.generate_partial(entities)

        progress("writing", 0.8)
        self.wiki_gen.write_partial(ctx.repo_path, wiki_pages)

        progress("embedding", 0.95)
        self.embedder.update_index(ctx.repo_path, wiki_pages)

        progress("done", 1.0)
```

---

### 2.2 Scanner 服务

```python
# backend/services/scanner.py
import os
import fnmatch
from pathlib import Path
from typing import List

class Scanner:
    # 硬编码排除（不可修改）
    HARD_EXCLUDES = ['.code-wiki/']

    # 默认排除（用户可取消）
    DEFAULT_EXCLUDES = [
        '__pycache__/', '.git/', 'node_modules/', '.venv/',
        'dist/', 'build/', '*.pyc',
    ]

    def __init__(self, config: dict):
        self.repo_path = config.get('repo_path', '')
        self.user_excludes = config.get('exclude_patterns', [])

    @property
    def all_excludes(self) -> List[str]:
        """合并所有排除规则：硬编码 + 默认 + 用户自定义"""
        return self.HARD_EXCLUDES + self.DEFAULT_EXCLUDES + self.user_excludes

    def is_excluded(self, relative_path: str) -> bool:
        """检查路径是否匹配任一排除规则"""
        for pattern in self.all_excludes:
            if fnmatch.fnmatch(relative_path, pattern):
                return True
            # 目录匹配：pattern 是 'dir/' 时匹配 'dir' 和 'dir/**'
            if pattern.endswith('/') and (
                relative_path == pattern[:-1] or
                relative_path.startswith(pattern)
            ):
                return True
        return False

    def scan_all(self, repo_path: str) -> List[str]:
        """全量扫描：返回所有 .py 文件（排除过滤后）"""
        py_files = []
        for root, dirs, files in os.walk(repo_path):
            # 原地过滤目录：排除的目录不下钻
            dirs[:] = [
                d for d in dirs
                if not self.is_excluded(
                    os.path.relpath(os.path.join(root, d), repo_path) + '/'
                )
            ]
            for f in files:
                rel = os.path.relpath(os.path.join(root, f), repo_path)
                if f.endswith('.py') and not self.is_excluded(rel):
                    py_files.append(rel)
        return py_files

    def scan_partial(self, repo_path: str, target_files: List[str]) -> List[str]:
        """部分扫描：仅返回指定的文件（仍需通过排除检查）"""
        return [f for f in target_files if not self.is_excluded(f)]

    def get_file_tree(self, repo_path: str) -> List[dict]:
        """构建文件树（用于前端展示），标记每个节点的排除和分析状态"""
        # 递归构建树结构，附加 status 和 excluded 字段
        ...
```

---

### 2.3 Analyzer 服务

```python
# backend/services/analyzer.py
import ast
from typing import List, Dict, Optional
from dataclasses import dataclass, field

@dataclass
class FunctionInfo:
    name: str
    docstring: Optional[str]
    args: List[dict]           # [{name, type_annotation, default}]
    returns: Optional[str]     # 返回类型注解
    start_line: int
    end_line: int
    decorators: List[str]

@dataclass
class ClassInfo:
    name: str
    docstring: Optional[str]
    bases: List[str]           # 父类名
    methods: List[FunctionInfo]
    start_line: int
    end_line: int
    decorators: List[str]

@dataclass
class ModuleInfo:
    path: str                  # 相对路径，如 'services/user.py'
    docstring: Optional[str]
    imports: List[str]         # import 的模块路径
    classes: List[ClassInfo]
    functions: List[FunctionInfo]  # 模块级函数
    total_lines: int

class Analyzer:
    def analyze_file(self, repo_path: str, rel_path: str) -> ModuleInfo:
        """分析单个 .py 文件，提取 AST 实体"""
        full_path = os.path.join(repo_path, rel_path)
        with open(full_path, 'r', encoding='utf-8') as f:
            source = f.read()

        tree = ast.parse(source)
        total_lines = len(source.splitlines())

        imports = self._extract_imports(tree)
        docstring = ast.get_docstring(tree)

        classes = []
        functions = []

        for node in ast.iter_child_nodes(tree):
            if isinstance(node, ast.ClassDef):
                classes.append(self._extract_class(node))
            elif isinstance(node, ast.FunctionDef):
                functions.append(self._extract_function(node))

        return ModuleInfo(
            path=rel_path,
            docstring=docstring,
            imports=imports,
            classes=classes,
            functions=functions,
            total_lines=total_lines,
        )

    def _extract_class(self, node: ast.ClassDef) -> ClassInfo:
        bases = [self._name_of(b) for b in node.bases]
        methods = [
            self._extract_function(n)
            for n in ast.iter_child_nodes(node)
            if isinstance(n, ast.FunctionDef)
        ]
        return ClassInfo(
            name=node.name,
            docstring=ast.get_docstring(node),
            bases=bases,
            methods=methods,
            start_line=node.lineno,
            end_line=node.end_lineno or node.lineno,
            decorators=[self._name_of(d) for d in node.decorator_list],
        )

    def _extract_function(self, node: ast.FunctionDef) -> FunctionInfo:
        args = []
        for arg in node.args.args:
            args.append({
                'name': arg.arg,
                'type_annotation': self._annotation_of(arg.annotation),
            })
        return FunctionInfo(
            name=node.name,
            docstring=ast.get_docstring(node),
            args=args,
            returns=self._annotation_of(node.returns),
            start_line=node.lineno,
            end_line=node.end_lineno or node.lineno,
            decorators=[self._name_of(d) for d in node.decorator_list],
        )

    def analyze_batch(self, files: List[str]) -> Dict[str, ModuleInfo]:
        """批量分析，返回 {rel_path: ModuleInfo}"""
        return {f: self.analyze_file(self.repo_path, f) for f in files}

    def build_dependency_graph(self, modules: Dict[str, ModuleInfo]) -> Dict[str, List[str]]:
        """构建依赖图：{module_path: [imported_module_paths]}"""
        graph = {}
        for path, info in modules.items():
            graph[path] = [
                imp for imp in info.imports
                if imp in modules  # 仅包含仓库内部依赖
            ]
        return graph

    def find_affected_files(self, changed_files: List[str], dep_graph: Dict[str, List[str]]) -> List[str]:
        """找到所有导入了变更模块的文件（反向依赖）"""
        affected = set(changed_files)
        for file, imports in dep_graph.items():
            if any(changed in imports for changed in changed_files):
                affected.add(file)
        return list(affected)

    # --- 私有辅助 ---
    def _name_of(self, node) -> str: ...
    def _annotation_of(self, node) -> Optional[str]: ...
    def _extract_imports(self, tree: ast.Module) -> List[str]: ...
```

---

### 2.4 Wiki Generator 服务

```python
# backend/services/wiki_generator.py
import os
import json
from datetime import datetime
from typing import List, Dict
from dataclasses import dataclass

@dataclass
class WikiPage:
    rel_path: str          # 对应源码路径，如 'services/user.py'
    markdown: str          # 生成的 Markdown 内容
    source_anchors: int    # 锚点数量

class WikiGenerator:
    def __init__(self, llm_client, config: dict):
        self.llm = llm_client
        self.model = config.get('llm_model', 'deepseek-v4-flash')
        self.temperature = config.get('llm_temperature', 0.3)

    def _build_prompt(self, module: ModuleInfo) -> str:
        """构造发给 DeepSeek 的 Prompt，输入为结构化 AST 摘要"""
        return f"""你是一个代码文档专家。根据以下 Python 模块的结构化信息，生成一份 Markdown 格式的 Wiki 文档。

要求：
1. 使用中文撰写
2. 每个实体（模块、类、方法）的描述后，用 [@src:{module.path}:{行号}] 标注源码位置
3. 包含：模块概述、类列表（含方法表格）、模块级函数、依赖关系
4. 只输出 Markdown，不要额外解释

模块路径: {module.path}
模块描述: {module.docstring or '无'}
总行数: {module.total_lines}

类:
{self._format_classes(module.classes)}

模块级函数:
{self._format_functions(module.functions)}

依赖:
{', '.join(module.imports) if module.imports else '无'}
"""

    async def generate_all(self, entities: Dict[str, ModuleInfo], dep_graph: Dict[str, List[str]]) -> List[WikiPage]:
        """全量生成：为每个模块生成 Wiki 页面"""
        pages = []

        # 首先生成架构概览
        index_md = await self._generate_index(entities, dep_graph)
        pages.append(WikiPage(rel_path='index.md', markdown=index_md, source_anchors=0))

        # 逐个模块生成
        for path, module in entities.items():
            md = await self._generate_single(module)
            pages.append(WikiPage(
                rel_path=path.replace('.py', '.md'),
                markdown=md,
                source_anchors=md.count('[@src:'),
            ))

        return pages

    async def _generate_single(self, module: ModuleInfo) -> str:
        """调用 DeepSeek API 生成单个模块的 Wiki"""
        prompt = self._build_prompt(module)
        response = await self.llm.chat(
            model=self.model,
            messages=[{'role': 'user', 'content': prompt}],
            temperature=self.temperature,
        )
        return response.content

    async def _generate_index(self, entities, dep_graph) -> str:
        """生成架构概览 index.md"""
        # 构造项目结构概览 + Mermaid 依赖图
        ...

    def write_all(self, repo_path: str, pages: List[WikiPage]):
        """全量写入：清除旧文件，写入新文件"""
        wiki_dir = os.path.join(repo_path, '.code-wiki')
        # 清除旧的 .md 文件（保留 config.json 和 chroma/）
        for root, dirs, files in os.walk(wiki_dir):
            if 'chroma' in dirs:
                dirs.remove('chroma')  # 不清除 Chroma 数据
            for f in files:
                if f.endswith('.md'):
                    os.remove(os.path.join(root, f))

        # 写入新文件
        for page in pages:
            target_dir = os.path.join(wiki_dir, os.path.dirname(page.rel_path))
            os.makedirs(target_dir, exist_ok=True)
            target_path = os.path.join(wiki_dir, page.rel_path)
            with open(target_path, 'w', encoding='utf-8') as f:
                f.write(page.markdown)

        # 更新 state.json
        self._update_state(repo_path, pages)

    def write_partial(self, repo_path: str, pages: List[WikiPage]):
        """部分写入：仅覆盖指定文件"""
        wiki_dir = os.path.join(repo_path, '.code-wiki')
        for page in pages:
            target_path = os.path.join(wiki_dir, page.rel_path)
            os.makedirs(os.path.dirname(target_path), exist_ok=True)
            with open(target_path, 'w', encoding='utf-8') as f:
                f.write(page.markdown)
        self._update_state(repo_path, pages, mode='partial')

    def _update_state(self, repo_path, pages, mode='full'):
        state_path = os.path.join(repo_path, '.code-wiki', 'state.json')
        state = {
            'last_analysis': datetime.now().isoformat(),
            'mode': mode,
            'total_pages': len(pages),
            'total_anchors': sum(p.source_anchors for p in pages),
            'llm_model': self.model,
        }
        with open(state_path, 'w') as f:
            json.dump(state, f, indent=2, ensure_ascii=False)
```

---

### 2.5 Chat & RAG 服务

```python
# backend/services/chat_service.py
import chromadb
from typing import List, AsyncGenerator

class ChatService:
    def __init__(self, llm_client, embedder, repo_path: str):
        self.llm = llm_client
        self.embedder = embedder
        self.chroma_client = chromadb.PersistentClient(
            path=os.path.join(repo_path, '.code-wiki', 'chroma')
        )

    async def chat_stream(
        self, question: str, history: List[dict], model: str
    ) -> AsyncGenerator[str, None]:
        """
        RAG 问答流水线 (SSE 流式)：
        1. 将 question 向量化
        2. 在 Chroma 中检索 Top-5 相关 Wiki chunk
        3. 拼接上下文 → DeepSeek Chat → 流式输出
        """
        # Step 1: 检索相关 Wiki chunk
        collection = self.chroma_client.get_collection('wiki_chunks')
        results = collection.query(
            query_texts=[question],
            n_results=5,
        )

        # Step 2: 构造上下文
        chunks = results['documents'][0] if results['documents'] else []
        metadatas = results['metadatas'][0] if results['metadatas'] else []
        sources = [m['source'] for m in metadatas] if metadatas else []

        context = '\n\n---\n\n'.join(chunks)

        # Step 3: 构造 Prompt
        system_prompt = f"""你是一个代码库问答助手。根据以下 Wiki 文档片段回答用户问题。

规则：
- 只能基于提供的 Wiki 片段回答，不要编造信息
- 如引用具体代码位置，使用 [src:path:line] 格式标注
- 如果 Wiki 中没有相关信息，直接说"未在文档中找到相关信息"
- 用中文回答

Wiki 文档片段：
{context}"""

        messages = [
            {'role': 'system', 'content': system_prompt},
            *history[-10:],   # 最近 10 轮对话
            {'role': 'user', 'content': question},
        ]

        # Step 4: 流式调用 DeepSeek
        stream = await self.llm.chat_stream(
            model=model,
            messages=messages,
            temperature=0.3,
        )

        async for chunk in stream:
            yield chunk  # SSE: data: {chunk}\n\n

        # 最后发送引用来源
        yield f'\n\n---\n📚 **参考来源：**\n'
        for src in set(sources):
            yield f'- [@src:{src}]\n'
```

---

## 3. Tauri Shell 层

```rust
// src-tauri/src/main.rs (关键函数签名)

// 窗口创建 + Sidecar 管理
fn main() {
    tauri::Builder::default()
        .setup(|app| {
            // 启动 FastAPI sidecar
            let sidecar = app.shell().sidecar("backend").spawn()?;
            app.manage(sidecar);
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![
            pick_repository,
            open_in_editor,
            get_system_theme,
        ])
        .run(tauri::generate_context!())
        .expect("error running tauri app");
}

// src-tauri/src/commands.rs
#[tauri::command]
async fn pick_repository() -> Result<String, String> {
    let path = rfd::FileDialog::new().pick_folder();
    path.map(|p| p.to_string_lossy().to_string())
        .ok_or_else(|| "用户取消选择".into())
}

#[tauri::command]
async fn open_in_editor(path: String, line: u32) -> Result<(), String> {
    // Windows: 尝试 VS Code / Cursor 协议
    #[cfg(target_os = "windows")]
    {
        // 优先尝试 cursor:// 协议
        let cursor_url = format!("cursor://file/{}:{}", path, line);
        if open::that(&cursor_url).is_err() {
            // 回退到 vscode:// 协议
            let vscode_url = format!("vscode://file/{}:{}", path, line);
            open::that(&vscode_url).map_err(|e| e.to_string())?;
        }
    }
    // macOS / Linux: 尝试 cursor / code 命令
    #[cfg(not(target_os = "windows"))]
    {
        // 优先 cursor，回退 code，再回退系统默认编辑器
        ...
    }
    Ok(())
}

// src-tauri/src/watcher.rs
use notify::{Watcher, RecursiveMode, Event};
use std::sync::mpsc;

pub fn start_watcher(repo_path: &str, tx: mpsc::Sender<Vec<String>>) {
    let (watcher_tx, watcher_rx) = mpsc::channel();
    let mut watcher = notify::recommended_watcher(move |res: Result<Event, _>| {
        if let Ok(event) = res {
            watcher_tx.send(event).ok();
        }
    }).unwrap();

    watcher.watch(repo_path.as_ref(), RecursiveMode::Recursive).unwrap();

    // 500ms 防抖合并
    let mut pending: Vec<String> = Vec::new();
    let mut last_flush = std::time::Instant::now();

    for event in watcher_rx {
        for path in event.paths {
            let rel = path.strip_prefix(repo_path).unwrap();
            if rel.starts_with(".code-wiki") { continue; }  // 忽略自身产物
            pending.push(rel.to_string_lossy().to_string());
        }

        if last_flush.elapsed() > std::time::Duration::from_millis(500) {
            if !pending.is_empty() {
                tx.send(pending.drain(..).collect()).ok();
            }
            last_flush = std::time::Instant::now();
        }
    }
}
```

---

## 4. 数据模型

```python
# backend/models/entities.py
from dataclasses import dataclass, field
from typing import List, Optional, Dict
from datetime import datetime

@dataclass
class SourceAnchor:
    """源码位置锚点"""
    file: str       # 相对路径
    line: int       # 行号

@dataclass
class FunctionInfo:
    name: str
    docstring: Optional[str]
    args: List[dict]         # [{name, type_annotation, default}]
    returns: Optional[str]
    anchor: SourceAnchor     # 起始行
    end_line: int
    decorators: List[str]

@dataclass
class ClassInfo:
    name: str
    docstring: Optional[str]
    bases: List[str]
    methods: List[FunctionInfo]
    anchor: SourceAnchor
    end_line: int
    decorators: List[str]

@dataclass
class ModuleInfo:
    path: str                # 相对路径
    docstring: Optional[str]
    imports: List[str]       # 导入的模块路径
    classes: List[ClassInfo]
    functions: List[FunctionInfo]
    total_lines: int

@dataclass
class WikiPage:
    path: str                # 如 'services/user.md'
    source_path: str         # 对应源码 'services/user.py'
    markdown: str            # 完整 Markdown 内容
    anchors_count: int
    generated_at: datetime
    model: str               # 使用的 LLM 模型

@dataclass
class AnalysisState:
    status: str              # idle | scanning | analyzing | generating | done | error
    progress: float          # 0.0 - 1.0
    current_step: str        # 当前步骤描述
    started_at: Optional[datetime]
    finished_at: Optional[datetime]
    total_modules: int
    processed_modules: int
    error_message: Optional[str]
```

```typescript
// src/lib/types.ts (前端类型映射)
export interface FileTreeNode {
  name: string;
  path: string;
  type: 'file' | 'directory';
  status: 'analyzed' | 'pending' | 'analyzing';
  excluded: boolean;
  children?: FileTreeNode[];
}

export interface WikiTreeNode {
  name: string;
  path: string;           // Wiki .md 路径
  sourcePath?: string;    // 对应源码路径
  children?: WikiTreeNode[];
}

export interface AnalysisStatus {
  status: 'idle' | 'scanning' | 'analyzing' | 'generating' | 'done' | 'error';
  progress: number;       // 0-100
  currentStep: string;
  startedAt: string | null;
  finishedAt: string | null;
  totalModules: number;
  processedModules: number;
  errorMessage?: string;
}

export interface ChatMessage {
  role: 'user' | 'assistant';
  content: string;
}

export interface LLMConfig {
  apiKey: string;
  model: 'deepseek-v4-flash' | 'deepseek-v4-pro';
  baseUrl: string;
  temperature: number;
}

export interface AppConfig {
  repoPath: string;
  excludePatterns: string[];
  llm: LLMConfig;
  theme: 'light' | 'dark' | 'system';
}
```

---

## 5. SSE 事件流

### 5.1 事件格式

```
event: progress
data: {"step":"scanning","progress":15,"message":"正在扫描仓库文件..."}

event: progress
data: {"step":"analyzing","progress":35,"message":"正在分析 services/user.py"}

event: progress
data: {"step":"generating","progress":65,"message":"正在生成 Wiki: models/user.py"}

event: progress
data: {"step":"done","progress":100,"message":"分析完成: 15 个模块, 42 个类, 128 个函数"}

event: error
data: {"step":"generating","error":"LLM API 调用失败: Connection timeout"}
```

### 5.2 前端订阅

```typescript
// hooks/useSSE.ts
export function useSSE() {
  const setAnalysisStatus = useConfigStore(s => s.setAnalysisStatus);

  useEffect(() => {
    const eventSource = new EventSource('/api/events');

    eventSource.addEventListener('progress', (e) => {
      const data = JSON.parse(e.data);
      setAnalysisStatus(data);
    });

    eventSource.addEventListener('error', (e) => {
      const data = JSON.parse(e.data);
      setAnalysisStatus({ status: 'error', ...data });
    });

    return () => eventSource.close();
  }, []);
}
```

---

## 6. 错误处理策略

| 层级 | 错误场景 | 处理方式 |
|------|----------|----------|
| **LLM API** | 超时 / 限流 / Key 无效 | 重试 3 次（指数退避），失败则跳过该文件并在错误列表记录 |
| **LLM API** | 返回格式异常 | 回退到仅包含 AST 摘要的基础模板（不依赖 LLM） |
| **文件系统** | 读写 .code-wiki/ 失败 | Toast 通知用户检查权限，中止操作 |
| **AST 分析** | 语法错误的 .py 文件 | 跳过该文件，记录警告，继续分析其他文件 |
| **Chroma** | 向量数据库损坏 | 自动重建索引 |
| **SSE 连接** | 断连 | 前端自动重连（3s 间隔，最多 10 次） |
| **Sidecar** | FastAPI 进程崩溃 | Tauri 自动重启，UI 显示"重连中" |
| **大仓库** | 分析超过 5 分钟 | 后端超时设置 10 分钟 + 前端显示进度条 |

### 全局错误边界

```tsx
// App.tsx
<ErrorBoundary fallback={<ErrorFallback />}>
  <ThemeProvider>
    <AppShell />
    <ToastContainer />
  </ThemeProvider>
</ErrorBoundary>

// ErrorFallback 提供 "重试" 和 "重置" 按钮
```

---

*文档版本: v1.0 · 最后更新: 2026-06-26 · 状态: 待评审*
