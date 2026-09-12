import { useEffect, useRef, useState } from "react";
import type { FormEvent } from "react";
import { imageBlob, request } from "./api";
import {
  decodeIdentity,
  newConversation,
  readConversations,
  serializeConversations,
  storageKey,
} from "./storage";
import type {
  Asset,
  AssistantResponse,
  Conversation,
  ConversationState,
  DisplayItem,
  Identity,
  MemoryEvent,
  Ready,
} from "./types";
import Admin from "./admin";

const demos = [
  { id: "demo-blue-shirt", label: "蓝色衬衫" },
  { id: "demo-black-pants", label: "黑色长裤" },
  { id: "demo-white-shoes", label: "白色休闲鞋" },
];
const waiting = ["正在等待造型建议", "分析单品 · 检索灵感", "整理搭配思路"];
export function AssetImage({
  imageKey,
  token,
  alt,
}: {
  imageKey: string;
  token: string;
  alt: string;
}) {
  const [url, setUrl] = useState("");
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    let objectUrl = "";
    const controller = new AbortController();
    setUrl("");
    setFailed(false);
    imageBlob(imageKey, token, controller.signal)
      .then((blob) => {
        if (!controller.signal.aborted) {
          objectUrl = URL.createObjectURL(blob);
          setUrl(objectUrl);
        }
      })
      .catch(() => {
        if (!controller.signal.aborted) setFailed(true);
      });
    return () => {
      controller.abort();
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [imageKey, token]);
  return url ? (
    <img src={url} alt={alt} />
  ) : (
    <span className="image-placeholder" role="img" aria-label={alt}>
      {failed ? "图片已过期或暂不可用" : alt}
      <small>{failed ? "可重新上传继续咨询" : "载入图片…"}</small>
    </span>
  );
}
function TokenGate({ onLogin }: { onLogin: (token: string) => void }) {
  const [value, setValue] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  async function submit(e: FormEvent) {
    e.preventDefault();
    setError("");
    setBusy(true);
    try {
      decodeIdentity(value);
      await request("/auth/me", value.trim());
      onLogin(value.trim());
    } catch (e) {
      setError(e instanceof Error ? e.message : "无法验证身份");
    } finally {
      setBusy(false);
    }
  }
  return (
    <main className="gate">
      <div className="gate-art">
        <span className="eyebrow">SHOPPING QnA / PRIVATE STYLING</span>
        <h1>
          风格，
          <br />
          从一场对话
          <br />
          <em>开始。</em>
        </h1>
        <div className="art-line" />
        <p>
          你的衣橱，你的偏好。
          <br />
          一起找到属于你的搭配方式。
        </p>
        <span className="edition">THE STYLE EDIT / 01</span>
      </div>
      <form className="gate-form" onSubmit={submit}>
        <span className="eyebrow">DEVELOPMENT ACCESS</span>
        <h2>进入造型编辑室</h2>
        <p>粘贴本地开发令牌，开启私人穿搭对话。</p>
        <label htmlFor="token">开发 JWT</label>
        <textarea
          id="token"
          value={value}
          onChange={(e) => setValue(e.target.value)}
          placeholder="粘贴你的访问令牌"
          autoComplete="off"
          spellCheck={false}
          required
        />
        <p className="fine">令牌仅存于当前浏览器会话。身份由服务端验证。</p>
        {error && (
          <p role="alert" className="error">
            {error}
          </p>
        )}
        <button className="primary" disabled={busy}>
          {busy ? "正在验证…" : "进入编辑室 →"}
        </button>
        <details>
          <summary>如何获取开发令牌</summary>
          <p>在项目目录运行以下命令，替换租户与用户 UUID：</p>
          <code>
            docker compose exec api python -m src.auth --tenant-id
            &lt;租户UUID&gt; --user-id &lt;用户UUID&gt;
          </code>
        </details>
      </form>
    </main>
  );
}
function Theme() {
  const [theme, setTheme] = useState(() => {
    try {
      return localStorage.getItem("shopping-qna:theme") || "system";
    } catch {
      return "system";
    }
  });
  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    try {
      localStorage.setItem("shopping-qna:theme", theme);
    } catch {}
  }, [theme]);
  return (
    <label className="theme">
      外观
      <select
        aria-label="外观主题"
        value={theme}
        onChange={(e) => setTheme(e.target.value)}
      >
        <option value="system">跟随系统</option>
        <option value="light">浅色</option>
        <option value="dark">深色</option>
      </select>
    </label>
  );
}
function Outfit({
  response,
  token,
  onAction,
  disabled,
}: {
  response: AssistantResponse;
  token: string;
  onAction: (action: string, item?: DisplayItem) => void;
  disabled: boolean;
}) {
  const items = response.display_items || [];
  const result = response.result || {};
  return (
    <>
      <div className="outfit-heading">
        <span className="eyebrow">YOUR STYLE EDIT</span>
        <span>精选造型 / {String(items.length).padStart(2, "0")}</span>
      </div>
      {items.length > 0 && (
        <div className={`outfit-board count-${Math.min(items.length, 4)}`}>
          <span className="board-watermark" aria-hidden="true">
            The edit.
          </span>
          {items.map((item, index) => (
            <article className="outfit-item" key={item.item_id}>
              <div className="item-picture">
                <AssetImage
                  imageKey={item.object_key}
                  token={token}
                  alt={`${item.colors?.join("") || ""}${item.sub_category || item.category}`}
                />
              </div>
              <div className="item-caption">
                <span className="item-number">0{index + 1}</span>
                <strong>
                  {item.sub_category || item.category || "精选单品"}
                </strong>
              </div>
              <div className="item-actions">
                <button
                  disabled={disabled}
                  onClick={() => onAction("keep", item)}
                >
                  {response.conversation_state?.locked_item_ids.includes(
                    item.item_id,
                  )
                    ? "已保留"
                    : "保留这件"}
                </button>
                <button
                  disabled={disabled}
                  onClick={() => onAction("replace", item)}
                >
                  换一件
                </button>
                <button
                  disabled={disabled}
                  onClick={() => onAction("dislike", item)}
                >
                  不喜欢
                </button>
              </div>
            </article>
          ))}
        </div>
      )}
      {typeof result.verdict === "string" && <h3>{result.verdict}</h3>}
      {typeof result.summary === "string" && <p>{result.summary}</p>}
      {typeof result.clarification_question === "string" && (
        <p>{result.clarification_question}</p>
      )}
      {(["strengths", "issues", "changes", "suggestions"] as const).map(
        (key) =>
          Array.isArray(result[key]) &&
          (result[key] as unknown[]).length > 0 && (
            <div className="advice" key={key}>
              <span>
                {
                  {
                    strengths: "搭配亮点",
                    issues: "留意细节",
                    changes: "本次调整",
                    suggestions: "编辑建议",
                  }[key]
                }
              </span>
              <ul>
                {(result[key] as unknown[])
                  .filter((v) => typeof v === "string")
                  .map((v, i) => (
                    <li key={i}>{String(v)}</li>
                  ))}
              </ul>
            </div>
          ),
      )}
    </>
  );
}
function Workspace({
  token,
  identity,
  onLogout,
}: {
  token: string;
  identity: Identity;
  onLogout: () => void;
}) {
  const key = storageKey(identity);
  const [conversations, setConversations] = useState<Conversation[]>(() => {
    try {
      const saved = readConversations(localStorage.getItem(key));
      return saved.length ? saved : [newConversation()];
    } catch {
      return [newConversation()];
    }
  });
  const [active, setActive] = useState(conversations[0].threadId);
  const [text, setText] = useState("");
  const [images, setImages] = useState<string[]>([]);
  const [uploads, setUploads] = useState<
    { id: string; file: File; error: string; busy: boolean }[]
  >([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [menu, setMenu] = useState(false);
  const [picker, setPicker] = useState(false);
  const [ready, setReady] = useState<Ready | null>(null);
  const [events, setEvents] = useState<MemoryEvent[]>([]);
  const [eventBusy, setEventBusy] = useState("");
  const [waitIndex, setWaitIndex] = useState(0);
  const cursor = useRef("");
  const abort = useRef<AbortController | null>(null);
  const end = useRef<HTMLDivElement>(null);
  const input = useRef<HTMLTextAreaElement>(null);
  const sidebar = useRef<HTMLElement>(null);
  const menuButton = useRef<HTMLButtonElement>(null);
  const conversation = conversations.find((c) => c.threadId === active)!;
  useEffect(() => {
    try {
      localStorage.setItem(key, serializeConversations(conversations));
    } catch {
      setError("浏览器存储空间不足，当前会话可能无法在刷新后恢复。");
    }
  }, [conversations, key]);
  useEffect(() => () => abort.current?.abort(), []);
  useEffect(() => {
    if (busy && !matchMedia("(prefers-reduced-motion: reduce)").matches) {
      const id = setInterval(
        () => setWaitIndex((i) => (i + 1) % waiting.length),
        4000,
      );
      return () => clearInterval(id);
    }
  }, [busy]);
  useEffect(() => {
    const latest = conversation.messages.at(-1);
    if (latest?.role === "assistant") {
      document.getElementById(`message-${latest.id}`)?.scrollIntoView({ block: "start" });
    } else if (busy) {
      end.current?.scrollIntoView({ block: "nearest" });
    }
  }, [conversation.messages.length, busy]);
  useEffect(() => {
    if (!menu) return;
    const focusTimer = setTimeout(
      () => sidebar.current?.querySelector<HTMLElement>(".new-chat:not(:disabled)")?.focus(),
      220,
    );
    const escape = (event: KeyboardEvent) => {
      if (event.key === "Escape") closeMenu();
    };
    document.addEventListener("keydown", escape);
    return () => {
      clearTimeout(focusTimer);
      document.removeEventListener("keydown", escape);
    };
  }, [menu]);
  async function health() {
    try {
      setReady(await request<Ready>("/health/ready", token));
    } catch {
      setReady(null);
    }
  }
  useEffect(() => {
    void health();
    let stopped = false;
    let polling = false;
    async function poll() {
      if (stopped || polling || document.hidden) return;
      polling = true;
      try {
        const data = await request<{ cursor: string; events: MemoryEvent[] }>(
          `/assistant/memory-events?limit=20${cursor.current ? `&after=${encodeURIComponent(cursor.current)}` : ""}`,
          token,
        );
        if (!stopped) {
          cursor.current = data.cursor;
          setEvents((old) => {
            const map = new Map(old.map((e) => [e.event_id, e]));
            data.events.forEach((e) => map.set(e.event_id, e));
            return [...map.values()].slice(-40);
          });
        }
      } catch {
      } finally {
        polling = false;
      }
    }
    void poll();
    const interval = setInterval(poll, 10000);
    return () => {
      stopped = true;
      clearInterval(interval);
    };
  }, [token]);
  function update(id: string, fn: (c: Conversation) => Conversation) {
    setConversations((all) => all.map((c) => (c.threadId === id ? fn(c) : c)));
  }
  function choose(id: string) {
    if (busy || uploads.some((u) => u.busy)) return;
    setActive(id);
    setText("");
    setImages([]);
    setUploads([]);
    if (menu) closeMenu();
    setError("");
  }
  function create() {
    const c = newConversation();
    setConversations((old) => [c, ...old]);
    choose(c.threadId);
  }
  function closeMenu() {
    setMenu(false);
    requestAnimationFrame(() => menuButton.current?.focus());
  }
  async function upload(id: string, file: File) {
    setUploads((old) =>
      old.map((u) => (u.id === id ? { ...u, error: "", busy: true } : u)),
    );
    try {
      if (file.size > 10 * 1024 * 1024) throw Error("图片不能超过 10 MiB");
      if (!["image/jpeg", "image/png", "image/webp"].includes(file.type))
        throw Error("请选择 JPEG、PNG 或 WebP");
      const form = new FormData();
      form.set("thread_id", active);
      form.set("file", file);
      const result = await request<Asset>("/assets/images", token, form);
      setImages((old) => [...old, result.image_key]);
      setUploads((old) => old.filter((u) => u.id !== id));
    } catch (e) {
      setUploads((old) =>
        old.map((u) =>
          u.id === id
            ? {
                ...u,
                busy: false,
                error: e instanceof Error ? e.message : "上传失败",
              }
            : u,
        ),
      );
    }
  }
  function addFiles(files: FileList | null) {
    if (!files) return;
    const available = 4 - images.length - uploads.length;
    if (files.length > available) {
      setError("每次最多选择 4 张图片。");
      return;
    }
    const next = Array.from(files).map((file) => ({
      id: crypto.randomUUID(),
      file,
      error: "",
      busy: true,
    }));
    setUploads((old) => [...old, ...next]);
    next.forEach((u) => void upload(u.id, u.file));
  }
  async function send(
    message = text,
    state = conversation.state,
    imageKeys = images,
  ) {
    if (busy || (!message.trim() && !imageKeys.length)) return;
    const thread = active;
    const controller = new AbortController();
    abort.current = controller;
    setBusy(true);
    setError("");
    setNotice("");
    update(thread, (c) => ({
      ...c,
      title: c.messages.length
        ? c.title
        : message.trim().slice(0, 24) || "图片穿搭咨询",
      updatedAt: new Date().toISOString(),
      messages: [
        ...c.messages,
        { id: crypto.randomUUID(), role: "user", text: message, imageKeys },
      ],
    }));
    setText("");
    setImages([]);
    try {
      const response = await request<AssistantResponse>(
        "/assistant/message",
        token,
        {
          thread_id: thread,
          message,
          image_keys: imageKeys,
          conversation_state: state,
        },
        controller.signal,
      );
      update(thread, (c) => ({
        ...c,
        state: response.conversation_state,
        updatedAt: new Date().toISOString(),
        messages: [
          ...c.messages,
          {
            id: crypto.randomUUID(),
            role: "assistant",
            text: response.message,
            response,
          },
        ],
      }));
      void health();
    } catch (e) {
      if (!controller.signal.aborted) {
        setError(e instanceof Error ? e.message : "请求失败，请重试");
        setText(message);
        setImages(imageKeys);
      }
    } finally {
      setBusy(false);
    }
  }
  async function feedback(response: AssistantResponse, event: string) {
    await request("/assistant/feedback", token, {
      thread_id: active,
      run_id: response.run_id,
      event,
      idempotency_key: `${response.run_id}:${event}`,
    });
    setNotice(
      event === "thumbs_down"
        ? "已记录这次反馈"
        : "已记录，后续搭配会参考你的反馈",
    );
  }
  async function action(
    response: AssistantResponse,
    kind: string,
    item?: DisplayItem,
  ) {
    try {
      if (kind === "saved" || kind === "thumbs_up") {
        await feedback(response, kind);
        return;
      }
      if (!item) return;
      const label = `${item.colors?.join("") || ""}${item.sub_category || item.category}`;
      if (kind === "replace") {
        setText(`请把${label}换一件，`);
        input.current?.focus();
        return;
      }
      if (kind === "dislike") {
        await feedback(response, "thumbs_down");
        setText(`我不喜欢这件${label}，请排除它并换一件。`);
        input.current?.focus();
        return;
      }
      const state = conversation.state;
      if (state) {
        const next: ConversationState = {
          ...state,
          locked_item_ids: [
            ...new Set([...state.locked_item_ids, item.item_id]),
          ],
          excluded_item_ids: state.excluded_item_ids.filter(
            (id) => id !== item.item_id,
          ),
        };
        await send(`请保留这件${label}。`, next, []);
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "操作失败");
    }
  }
  async function decide(event: MemoryEvent, action: string) {
    setEventBusy(event.event_id);
    try {
      const result = await request<{
        event_id: string;
        status: string;
        reversible_until: string | null;
      }>(`/assistant/memory-events/${event.event_id}/decision`, token, {
        action,
      });
      setEvents((old) =>
        old.map((e) =>
          e.event_id === event.event_id
            ? { ...e, ...result, requires_confirmation: false }
            : e,
        ),
      );
      setNotice(
        action === "undo"
          ? "已撤销这次记忆更新"
          : action === "confirm"
            ? "已确认记忆"
            : "这条偏好不会被记住",
      );
    } catch (e) {
      setError(e instanceof Error ? e.message : "记忆操作失败");
    } finally {
      setEventBusy("");
    }
  }
  const uploading = uploads.some((u) => u.busy);
  return (
    <div className="app-shell">
      {menu && (
        <button
          className="drawer-backdrop"
          aria-label="关闭会话栏"
          onClick={closeMenu}
        />
      )}
      <aside id="conversation-drawer" ref={sidebar} className={`sidebar ${menu ? "open" : ""}`}>
        <a className="brand" href="/">
          SQ
          <span>
            ShoppingQnA<small>造型编辑室</small>
          </span>
        </a>
        <button
          className="new-chat"
          disabled={busy || uploading}
          onClick={create}
        >
          ＋ 新的造型对话
        </button>
        <span className="eyebrow sidebar-label">YOUR CONVERSATIONS</span>
        <nav aria-label="本地会话">
          {conversations.map((c) => (
            <div
              className={`conversation-row ${active === c.threadId ? "selected" : ""}`}
              key={c.threadId}
            >
              <button
                disabled={busy || uploading}
                onClick={() => choose(c.threadId)}
              >
                {c.title}
              </button>
              <details>
                <summary aria-label={`${c.title}的操作`}>···</summary>
                <div className="conversation-menu">
                  <button
                    disabled={busy || uploading}
                    onClick={() => {
                      const title = prompt("会话名称", c.title);
                      if (title?.trim())
                        update(c.threadId, (old) => ({
                          ...old,
                          title: title.trim().slice(0, 80),
                        }));
                    }}
                  >
                    重命名
                  </button>
                  <button
                    disabled={busy || uploading}
                    onClick={() => {
                      if (
                        !confirm("删除此浏览器中的会话记录？后端记忆不受影响。")
                      )
                        return;
                      const next = conversations.filter(
                        (x) => x.threadId !== c.threadId,
                      );
                      if (!next.length) next.push(newConversation());
                      setConversations(next);
                      if (active === c.threadId) choose(next[0].threadId);
                    }}
                  >
                    删除
                  </button>
                </div>
              </details>
            </div>
          ))}
        </nav>
        <div className="sidebar-bottom">
          <button className="service-status" onClick={health}>
            <i className={ready?.status === "ready" ? "online" : ""} />
            {ready?.status === "ready"
              ? "编辑室已就绪"
              : ready
                ? "服务需要预热"
                : "检查服务连接"}
            <span>↻</span>
          </button>
          <Theme />
          <div className="identity">
            <span className="avatar">U</span>
            <div>
              私人造型空间
              <small>
                {identity.sub.slice(0, 8)} · {identity.tenant_id.slice(0, 8)}
              </small>
            </div>
            <button
              title="退出开发身份"
              aria-label="退出开发身份"
              onClick={onLogout}
            >
              ↗
            </button>
          </div>
        </div>
      </aside>
      <main className="workspace" inert={menu || undefined}>
        <header className="topbar">
          <button
            ref={menuButton}
            className="mobile-menu"
            aria-label="打开会话栏"
            aria-controls="conversation-drawer"
            aria-expanded={menu}
            onClick={() => setMenu(true)}
          >
            ☰
          </button>
          <span>THE STYLE EDIT</span>
          <span className="topbar-caption">日常灵感，与你有关。</span>
        </header>
        <div className="chat-scroll">
          {conversation.messages.length === 0 ? (
            <section className="welcome">
              <span className="eyebrow">YOUR PERSONAL STYLE, REIMAGINED</span>
              <h1>
                今天，
                <br />
                想穿出怎样的<em>自己？</em>
              </h1>
              <p>
                从一件喜欢的单品开始。上传照片，
                <br className="desktop-only" />
                或告诉我你的想法，一起把灵感穿在身上。
              </p>
              <div className="starter-grid">
                {[
                  "帮我搭配一套通勤穿搭",
                  "看看这几件衣服搭不搭",
                  "推荐一件简约的蓝色衬衫",
                ].map((v, i) => (
                  <button
                    key={v}
                    onClick={() => {
                      setText(v);
                      input.current?.focus();
                    }}
                  >
                    <span>0{i + 1}</span>
                    {v}
                    <span>↗</span>
                  </button>
                ))}
              </div>
              <p className="welcome-note">上传自己的单品，或选择演示商品体验</p>
            </section>
          ) : (
            <section className="messages" aria-label="穿搭对话" aria-live="polite" aria-relevant="additions">
              {conversation.messages.map((m) => (
                <article id={`message-${m.id}`} key={m.id} className={`message ${m.role}`}>
                  <div className="message-label">
                    {m.role === "user" ? "YOU" : "SQ / 造型编辑"}
                  </div>
                  {m.text && <p className="message-text">{m.text}</p>}
                  {m.imageKeys && (
                    <div className="user-images">
                      {m.imageKeys.map((k) => (
                        <AssetImage
                          key={k}
                          imageKey={k}
                          token={token}
                          alt="上传的穿搭单品"
                        />
                      ))}
                    </div>
                  )}
                  {m.response && (
                    <>
                      <Outfit
                        response={m.response}
                        token={token}
                        disabled={busy}
                        onAction={(kind, item) =>
                          void action(m.response!, kind, item)
                        }
                      />
                      {m.response.status === "ok" && (
                        <div className="response-actions">
                          <button
                            onClick={() =>
                              void action(m.response!, "thumbs_up")
                            }
                          >
                            ♡ 喜欢这个方向
                          </button>
                          <button
                            onClick={() => void action(m.response!, "saved")}
                          >
                            ＋ 收藏这次搭配
                          </button>
                        </div>
                      )}
                    </>
                  )}
                </article>
              ))}
            </section>
          )}
          {busy && (
            <div className="waiting">
              <span className="sr-only" role="status">正在准备穿搭结果。</span>
              <span className="waiting-dot" />
              <span aria-hidden="true">
                {waiting[waitIndex]}
                <small>等待提示，并非实时执行进度</small>
              </span>
            </div>
          )}
          <div className="memory-events">
            {events
              .filter(
                (e) =>
                  !["rejected", "undone", "expired"].includes(e.status || ""),
              )
              .map((e) => (
                <div className="memory-notice" role="status" key={e.event_id}>
                  <span>✧</span>
                  <p>
                    {e.requires_confirmation ? "要记住这个偏好吗？" : "已记住"}
                    <strong>{e.summary}</strong>
                  </p>
                  {e.requires_confirmation ? (
                    <>
                      <button
                        disabled={eventBusy === e.event_id}
                        onClick={() => void decide(e, "confirm")}
                      >
                        记住
                      </button>
                      <button
                        disabled={eventBusy === e.event_id}
                        onClick={() => void decide(e, "reject")}
                      >
                        不用
                      </button>
                    </>
                  ) : (
                    e.reversible_until &&
                    Date.parse(e.reversible_until) > Date.now() && (
                      <button
                        disabled={eventBusy === e.event_id}
                        onClick={() => void decide(e, "undo")}
                      >
                        撤销
                      </button>
                    )
                  )}
                </div>
              ))}
          </div>
          <div ref={end} />
        </div>
        <div className="composer-wrap">
          {ready && ready.status !== "ready" && (
            <div className="readiness">
              {ready.status === "warming"
                ? "模型正在预热，首次请求可能较慢。"
                : "演示数据或模型尚未就绪，请完成 Docker 初始化。"}
              {identity.roles.includes("tenant_admin") && (
                <button
                  onClick={() =>
                    void request<Ready>("/warmup", token, {})
                      .then(setReady)
                      .catch((e) => setError(e.message))
                  }
                >
                  预热
                </button>
              )}
            </div>
          )}
          {error && (
            <div role="alert" className="error banner">
              {error}
              <button onClick={() => setError("")} aria-label="关闭错误">
                ×
              </button>
            </div>
          )}
          {notice && (
            <div role="status" className="notice">
              {notice}
            </div>
          )}
          <form
            className="composer"
            onSubmit={(e) => {
              e.preventDefault();
              void send();
            }}
          >
            {(images.length > 0 || uploads.length > 0) && (
              <div className="attachments">
                {images.map((k) => (
                  <div className="attachment" key={k}>
                    <AssetImage imageKey={k} token={token} alt="待发送单品" />
                    <button
                      type="button"
                      aria-label="移除图片"
                      onClick={() =>
                        setImages((old) => old.filter((x) => x !== k))
                      }
                    >
                      ×
                    </button>
                  </div>
                ))}
                {uploads.map((u) => (
                  <div className="upload-state" key={u.id}>
                    <span>{u.file.name}</span>
                    <small>{u.busy ? "正在上传…" : u.error}</small>
                    {!u.busy && (
                      <>
                        <button
                          type="button"
                          onClick={() => void upload(u.id, u.file)}
                        >
                          重试
                        </button>
                        <button
                          type="button"
                          onClick={() =>
                            setUploads((old) =>
                              old.filter((x) => x.id !== u.id),
                            )
                          }
                        >
                          移除
                        </button>
                      </>
                    )}
                  </div>
                ))}
              </div>
            )}
            <textarea
              ref={input}
              aria-label="穿搭需求"
              value={text}
              onChange={(e) => setText(e.target.value)}
              onKeyDown={(e) => {
                if (
                  e.key === "Enter" &&
                  !e.shiftKey &&
                  !e.nativeEvent.isComposing
                ) {
                  e.preventDefault();
                  if (!busy && !uploading && !uploads.length) void send();
                }
              }}
              placeholder="告诉我你的穿搭想法，或上传单品照片…"
              rows={2}
            />
            <div className="composer-tools">
              <label
                className={`upload-button ${busy ? "disabled" : ""}`}
              >
                ＋ 添加图片
                <input
                  type="file"
                  accept="image/jpeg,image/png,image/webp"
                  multiple
                  disabled={busy}
                  onChange={(e) => {
                    addFiles(e.target.files);
                    e.target.value = "";
                  }}
                />
              </label>
              <button
                type="button"
                disabled={busy}
                onClick={() => setPicker(!picker)}
              >
                演示商品
              </button>
              <span className="composer-hint">
                Enter 发送 · Shift + Enter 换行
              </span>
              <button
                className="send"
                aria-label="发送消息"
                disabled={
                  busy ||
                  uploading ||
                  uploads.length > 0 ||
                  (!text.trim() && !images.length)
                }
              >
                ↑
              </button>
            </div>
            {picker && (
              <div className="demo-picker">
                <p>开发演示单品 · 合成色块图片，不是真实商品摄影</p>
                {demos.map((d) => (
                  <button
                    type="button"
                    disabled={
                      images.length + uploads.length >= 4 ||
                      images.includes(`demo/items/${d.id}.jpg`)
                    }
                    key={d.id}
                    onClick={() =>
                      setImages((old) => [...old, `demo/items/${d.id}.jpg`])
                    }
                  >
                    {d.label} ＋
                  </button>
                ))}
              </div>
            )}
          </form>
          <p className="composer-footnote">
            搭配建议仅供参考 · 对话记录保存在此浏览器
          </p>
        </div>
      </main>
    </div>
  );
}
export default function App() {
  const [token, setToken] = useState(() => {
    try {
      return sessionStorage.getItem("shopping-qna:token") || "";
    } catch {
      return "";
    }
  });
  let identity: Identity | null = null;
  try {
    if (token) identity = decodeIdentity(token);
  } catch {}
  function logout() {
    try {
      sessionStorage.removeItem("shopping-qna:token");
    } catch {}
    setToken("");
  }
  useEffect(() => {
    window.addEventListener("auth-expired", logout);
    return () => window.removeEventListener("auth-expired", logout);
  }, []);
  useEffect(() => {
    if (!identity && token) logout();
  }, [token]);
  if (!identity)
    return (
      <TokenGate
        onLogin={(value) => {
          try {
            sessionStorage.setItem("shopping-qna:token", value);
            setToken(value);
          } catch {
            throw Error("浏览器禁止会话存储，请允许后重试。");
          }
        }}
      />
    );
  return location.pathname.replace(/\/$/, "") === "/admin" ? (
    <Admin token={token} identity={identity} onLogout={logout} />
  ) : (
    <Workspace
      key={storageKey(identity)}
      token={token}
      identity={identity}
      onLogout={logout}
    />
  );
}
