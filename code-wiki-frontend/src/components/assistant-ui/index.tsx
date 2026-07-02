import {
  ThreadPrimitive, ComposerPrimitive, MessagePrimitive,
  ActionBarPrimitive, BranchPickerPrimitive, SelectionToolbarPrimitive,
  useLocalRuntime, AssistantRuntimeProvider,
} from "@assistant-ui/react";
import { SSEChatModelAdapter } from "@/lib/chat/sseAdapter";
import { MarkdownHooks } from "react-markdown";
import remarkGfm from "remark-gfm";
import { rehypePrettyCodePlugin } from "@/components/wiki/rehypePrettyCode";
import { cn } from "@/lib/utils";
import { Suspense } from "react";
import type { ComponentProps } from "react";
import type { TextMessagePartComponent } from "@assistant-ui/react";
import {
  CopyIcon, RefreshCwIcon, ThumbsUpIcon, ThumbsDownIcon,
  ChevronLeftIcon, ChevronRightIcon,
} from "lucide-react";

// ─── Runtime Provider ───

export function ChatRuntimeProvider({ children }: { children: React.ReactNode }) {
  const runtime = useLocalRuntime(new SSEChatModelAdapter());
  return (
    <AssistantRuntimeProvider runtime={runtime}>
      {children}
    </AssistantRuntimeProvider>
  );
}

// ─── Styled Thread ───

export function StyledThread({ className, ...props }: ComponentProps<typeof ThreadPrimitive.Root>) {
  return (
    <ThreadPrimitive.Root
      className={cn("flex flex-col h-full bg-background", className)}
      {...props}
    >
      <ThreadPrimitive.Viewport className="flex-1 min-h-0 overflow-y-auto px-4 py-3 space-y-3">
        <ThreadPrimitive.Empty>
          <div className="text-center mt-8">
            <p className="text-sm text-muted-foreground">
              基于最新 Wiki 回答代码问题
            </p>
            <p className="text-xs text-muted-foreground mt-1">
              输入问题后按 Enter 发送
            </p>
          </div>
        </ThreadPrimitive.Empty>
        <ThreadPrimitive.Messages>
          {() => <StyledMessage />}
        </ThreadPrimitive.Messages>
      </ThreadPrimitive.Viewport>
      <StyledComposer />
    </ThreadPrimitive.Root>
  );
}

// ─── Styled Composer ───

export function StyledComposer() {
  return (
    <ComposerPrimitive.Root className="p-3 border-t border-border shrink-0">
      <div className="flex gap-2">
        <ComposerPrimitive.Input
          placeholder="基于 Wiki 提问..."
          className="flex-1 px-3 py-2 text-sm rounded-md border border-input bg-background focus:outline-none focus:ring-1 focus:ring-primary resize-none"
          rows={1}
        />
        <ComposerPrimitive.Send className="px-3 py-2 rounded-md bg-primary text-primary-foreground hover:opacity-90 disabled:opacity-50 transition-opacity flex items-center gap-1 text-sm">
          发送
        </ComposerPrimitive.Send>
        <ComposerPrimitive.Cancel className="px-3 py-2 rounded-md border border-border hover:bg-accent transition-colors text-sm">
          取消
        </ComposerPrimitive.Cancel>
      </div>
    </ComposerPrimitive.Root>
  );
}

// ─── Styled Message ───

export function StyledMessage() {
  return (
    <MessagePrimitive.Root>
      {/* Assistant message — left-aligned secondary bubble */}
      <MessagePrimitive.If assistant={true}>
        <div className="flex justify-start">
          <div className="rounded-lg px-3 py-2 text-sm max-w-[80%] bg-secondary text-secondary-foreground">
            <MessagePrimitive.Content
              components={{
                Text: StyledMarkdownText,
              }}
            />
            {/* Branch picker — shown when multiple regenerated versions exist */}
            <BranchPickerPrimitive.Root
              hideWhenSingleBranch
              className="flex items-center gap-1 mt-2 pt-2 border-t border-border/40"
            >
              <BranchPickerPrimitive.Previous>
                <ChevronLeftIcon size={14} />
              </BranchPickerPrimitive.Previous>
              <span className="text-[11px] text-muted-foreground px-1">
                <BranchPickerPrimitive.Number /> / <BranchPickerPrimitive.Count />
              </span>
              <BranchPickerPrimitive.Next>
                <ChevronRightIcon size={14} />
              </BranchPickerPrimitive.Next>
            </BranchPickerPrimitive.Root>
          </div>
        </div>
        {/* Action bar — copy, regenerate, feedback */}
        <ActionBarPrimitive.Root
          hideWhenRunning
          autohide="not-last"
          autohideFloat="single-branch"
          className="flex items-center gap-1 ml-2 mt-1"
        >
          <ActionBarPrimitive.Copy>
            <CopyIcon size={14} />
          </ActionBarPrimitive.Copy>
          <ActionBarPrimitive.Reload>
            <RefreshCwIcon size={14} />
          </ActionBarPrimitive.Reload>
          <ActionBarPrimitive.FeedbackPositive>
            <ThumbsUpIcon size={14} />
          </ActionBarPrimitive.FeedbackPositive>
          <ActionBarPrimitive.FeedbackNegative>
            <ThumbsDownIcon size={14} />
          </ActionBarPrimitive.FeedbackNegative>
        </ActionBarPrimitive.Root>
      </MessagePrimitive.If>
      {/* User message — right-aligned primary bubble */}
      <MessagePrimitive.If user={true}>
        <div className="flex justify-end">
          <div className="rounded-lg px-3 py-2 text-sm max-w-[80%] bg-primary text-primary-foreground">
            <MessagePrimitive.Content
              components={{
                Text: StyledMarkdownText,
              }}
            />
          </div>
        </div>
      </MessagePrimitive.If>
      {/* Selection toolbar — floating toolbar on text selection */}
      <SelectionToolbarPrimitive.Root className="flex items-center gap-1 px-2 py-1 rounded-lg bg-popover border border-border shadow-lg text-xs">
        <SelectionToolbarPrimitive.Quote className="px-2 py-1 rounded hover:bg-accent transition-colors">
          引用
        </SelectionToolbarPrimitive.Quote>
      </SelectionToolbarPrimitive.Root>
    </MessagePrimitive.Root>
  );
}

// ─── Markdown Text Part Component ───

const StyledMarkdownText: TextMessagePartComponent = ({ text }) => {
  return (
    <Suspense fallback={<div className="animate-pulse h-3 bg-muted rounded" />}>
      <MarkdownHooks
        remarkPlugins={[remarkGfm]}
        rehypePlugins={[rehypePrettyCodePlugin] as any}
        className="prose prose-sm dark:prose-invert max-w-none"
      >
        {text}
      </MarkdownHooks>
    </Suspense>
  );
};
