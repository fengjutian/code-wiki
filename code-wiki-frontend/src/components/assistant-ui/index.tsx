import { ThreadPrimitive, ComposerPrimitive, MessagePrimitive, useLocalRuntime, AssistantRuntimeProvider } from "@assistant-ui/react";
import { SSEChatModelAdapter } from "@/lib/chat/sseAdapter";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { rehypePrettyCodePlugin } from "@/components/wiki/rehypePrettyCode";
import { cn } from "@/lib/utils";
import type { ComponentProps } from "react";
import type { TextMessagePartComponent } from "@assistant-ui/react";

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
      <ThreadPrimitive.Viewport className="flex-1 overflow-y-auto px-4 py-3 space-y-3">
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
          </div>
        </div>
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
    </MessagePrimitive.Root>
  );
}

// ─── Markdown Text Part Component ───

const StyledMarkdownText: TextMessagePartComponent = ({ text }) => {
  return (
    <ReactMarkdown
      remarkPlugins={[remarkGfm]}
      rehypePlugins={[rehypePrettyCodePlugin]}
      className="prose prose-sm dark:prose-invert max-w-none"
    >
      {text}
    </ReactMarkdown>
  );
};
