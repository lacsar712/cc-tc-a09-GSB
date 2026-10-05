<script>
  let session = null;
  let view = "logs"; // logs | roster
  let logs = [];
  let plates = { active: [], retired: [] };
  let events = [];
  let loginUser = "surveyor";
  let loginPass = "surv123456";
  let selectedPlate = "";
  let deltaMm = "";
  let newPlateNo = "";
  let newChainage = "";
  let error = "";
  let info = "";
  let loading = false;
  let timer;

  $: isWriter = session?.role === "writer";

  function headers() {
    return session ? { Authorization: "Bearer " + session.token } : {};
  }

  async function api(path, options = {}) {
    const res = await fetch(path, { headers: { ...headers(), ...(options.headers || {}) }, ...options });
    const data = await res.json().catch(() => ({}));
    return { ok: res.ok, status: res.status, data };
  }

  async function refreshLogs() {
    const { ok, status, data } = await api("/api/logs");
    if (status === 401) return logout();
    if (ok) logs = data;
  }

  async function refreshPlates() {
    const { ok, status, data } = await api("/api/plates");
    if (status === 401) return logout();
    if (ok) {
      plates = data;
      if (selectedPlate && !data.active.some((p) => p.plate_no === selectedPlate)) {
        selectedPlate = "";
      }
    }
  }

  async function refreshEvents() {
    const { ok, data } = await api("/api/plates/events");
    if (ok) events = data;
  }

  async function refreshRoster() {
    await Promise.all([refreshPlates(), refreshEvents()]);
  }

  async function login() {
    error = "";
    loading = true;
    try {
      const res = await fetch("/api/auth/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ username: loginUser, password: loginPass }),
      });
      const data = await res.json();
      if (!res.ok) {
        error = data.detail || "登录失败";
        return;
      }
      session = { token: data.access_token, username: data.username, role: data.role };
      localStorage.setItem("tunnel_session", JSON.stringify(session));
      await Promise.all([refreshLogs(), refreshPlates()]);
      timer = setInterval(refreshLogs, 2000);
    } catch {
      error = "无法连接接口";
    } finally {
      loading = false;
    }
  }

  function logout() {
    if (timer) clearInterval(timer);
    session = null;
    logs = [];
    plates = { active: [], retired: [] };
    events = [];
    localStorage.removeItem("tunnel_session");
  }

  async function submitLog() {
    error = "";
    if (!selectedPlate) {
      error = "必须从在役铭牌中选择一个号";
      return;
    }
    loading = true;
    try {
      const { ok, status, data } = await api("/api/logs", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ plate_no: selectedPlate, delta_mm: Number(deltaMm) }),
      });
      if (!ok) {
        error = data.detail || (status === 401 ? "未登录" : "提交失败");
        return;
      }
      deltaMm = "";
      await Promise.all([refreshLogs(), refreshPlates(), refreshEvents()]);
    } catch {
      error = "提交时网络异常";
    } finally {
      loading = false;
    }
  }

  async function registerPlate() {
    error = "";
    info = "";
    loading = true;
    try {
      const { ok, data } = await api("/api/plates", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ plate_no: newPlateNo, chainage: newChainage }),
      });
      if (!ok) {
        error = data.detail || "登记失败";
        return;
      }
      info = `铭牌 ${data.plate_no} 已登记为在役，履历已同次写入`;
      newPlateNo = "";
      newChainage = "";
      await refreshRoster();
    } catch {
      error = "登记时网络异常";
    } finally {
      loading = false;
    }
  }

  async function retirePlate(plate) {
    error = "";
    info = "";
    const reason = window.prompt(`退役 ${plate.plate_no}（${plate.chainage}）的原因？退役后旧绑定不可改。`);
    if (reason === null) return;
    loading = true;
    try {
      const { ok, data } = await api(`/api/plates/${encodeURIComponent(plate.plate_no)}/retire`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ reason }),
      });
      if (!ok) {
        error = data.detail || "退役失败";
        return;
      }
      info = `铭牌 ${data.plate_no} 已退役，状态与履历一次写齐`;
      if (selectedPlate === data.plate_no) selectedPlate = "";
      await refreshRoster();
    } catch {
      error = "退役时网络异常";
    } finally {
      loading = false;
    }
  }

  function gotoLogsWith(plateNo) {
    selectedPlate = plateNo;
    view = "logs";
    error = "";
  }

  async function switchView(v) {
    view = v;
    error = "";
    info = "";
    if (v === "roster") await refreshRoster();
  }

  function kindLabel(k) {
    return { register: "登记", bind: "绑定测缝", retire: "退役" }[k] || k;
  }
  function fmt(ts) {
    return ts ? new Date(ts).toLocaleString("zh-CN", { hour12: false }) : "—";
  }

  const raw = localStorage.getItem("tunnel_session");
  if (raw) {
    try {
      session = JSON.parse(raw);
      refreshLogs();
      refreshPlates();
      timer = setInterval(refreshLogs, 2000);
    } catch {
      localStorage.removeItem("tunnel_session");
    }
  }
</script>

<style>
  :global(body) {
    margin: 0;
    font-family: "Segoe UI", system-ui, sans-serif;
    background: #1c1917;
    color: #f5f5f4;
  }
  main { max-width: 1000px; margin: 0 auto; padding: 1.5rem; }
  header.top {
    display: flex; align-items: center; justify-content: space-between;
    border-bottom: 1px solid #44403c; padding-bottom: 0.75rem; margin-bottom: 1rem;
  }
  h1 { color: #fbbf24; margin: 0; font-size: 1.3rem; }
  nav { display: flex; gap: 0.5rem; }
  nav a {
    cursor: pointer; padding: 0.35rem 0.9rem; border-radius: 6px;
    background: #292524; border: 1px solid #57534e; color: #e7e5e4; font-size: 0.9rem;
  }
  nav a.active { background: #d97706; border-color: #d97706; color: #fff; }
  .sub { color: #a8a29e; margin-bottom: 1.25rem; font-size: 0.9rem; }
  section {
    background: #292524; border: 1px solid #44403c; border-radius: 8px;
    padding: 1rem 1.25rem; margin-bottom: 1rem;
  }
  h2 { font-size: 1.05rem; margin: 0 0 0.75rem; color: #fcd34d; }
  label { display: block; font-size: 0.85rem; color: #d6d3d1; margin-bottom: 0.25rem; }
  input, select {
    width: 100%; box-sizing: border-box; padding: 0.5rem 0.65rem; border-radius: 6px;
    border: 1px solid #57534e; background: #0c0a09; color: #fafaf9; margin-bottom: 0.75rem;
  }
  button {
    cursor: pointer; padding: 0.45rem 0.95rem; border: none; border-radius: 6px;
    background: #d97706; color: #fff; font-weight: 600; font-size: 0.88rem;
  }
  button.secondary { background: #57534e; }
  button:disabled { opacity: 0.5; cursor: not-allowed; }
  .err { color: #fb7185; }
  .ok-msg { color: #86efac; }
  table { width: 100%; border-collapse: collapse; font-size: 0.88rem; }
  th, td { text-align: left; padding: 0.45rem; border-bottom: 1px solid #44403c; vertical-align: top; }
  .tag { padding: 0.1rem 0.4rem; border-radius: 4px; font-size: 0.8rem; }
  .ok { background: #14532d; color: #86efac; }
  .bad { background: #7f1d1d; color: #fca5a5; }
  .pending { background: #713f12; color: #fde68a; }
  .note { background: #1c1917; border-left: 3px solid #d97706; padding: 0.6rem 0.8rem; border-radius: 4px; font-size: 0.86rem; color: #d6d3d1; }
  .example { font-family: ui-monospace, monospace; font-size: 0.84rem; color: #fde68a; }
  .rowline { display: flex; gap: 0.5rem; align-items: center; flex-wrap: wrap; font-size: 0.85rem; color: #a8a29e; }
</style>

<main>
  {#if !session}
    <h1>隧道收敛测缝台</h1>
    <p class="sub">没有在役铭牌不许报测缝。登录框已预填可写账号 surveyor / surv123456；巡检 inspector / insp123456 只读。</p>
    <section>
      <label>用户名</label>
      <input bind:value={loginUser} autocomplete="off" />
      <label>密码</label>
      <input type="password" bind:value={loginPass} autocomplete="off" />
      <button disabled={loading} on:click={login}>登录</button>
      {#if error}<p class="err">{error}</p>{/if}
    </section>
  {:else}
    <header class="top">
      <h1>隧道收敛测缝台</h1>
      <nav>
        <a class:active={view === "logs"} on:click={() => switchView("logs")}>测缝报送</a>
        <a class:active={view === "roster"} on:click={() => switchView("roster")}>铭牌册</a>
      </nav>
    </header>
    <p class="sub">
      已登录：{session.username}（{isWriter ? "测量员·可报送可改册" : "巡检岗·只读名册，不能改册"}）
      <button class="secondary" style="margin-left:0.75rem" on:click={logout}>退出</button>
    </p>
    {#if error}<p class="err">{error}</p>{/if}
    {#if info}<p class="ok-msg">{info}</p>{/if}

    {#if view === "logs"}
      {#if isWriter}
        <section>
          <h2>报测缝（只许点在役的号）</h2>
          <label>绑定在役铭牌（断面由铭牌册带入，不能手填）</label>
          <select bind:value={selectedPlate}>
            <option value="">— 请选择在役铭牌 —</option>
            {#each plates.active as p}
              <option value={p.plate_no}>{p.plate_no} · {p.chainage}</option>
            {/each}
          </select>
          {#if selectedPlate}
            <p class="rowline">将绑定断面：<b>{(plates.active.find((p) => p.plate_no === selectedPlate) || {}).chainage}</b></p>
          {/if}
          <label>收敛（毫米，可正可负）</label>
          <input type="number" step="0.1" bind:value={deltaMm} />
          <button disabled={loading} on:click={submitLog}>提交（进入待认领）</button>
          <p class="rowline" style="margin-top:0.5rem">退役号不出现在此列表；对退役号的报送会被整份退回，不产生单据。</p>
        </section>
      {/if}
      <section>
        <h2>测缝单（铭牌号 + 断面）</h2>
        <table>
          <thead>
            <tr><th>编号</th><th>铭牌号</th><th>断面</th><th>收敛mm</th><th>状态</th><th>结论</th><th>说明</th></tr>
          </thead>
          <tbody>
            {#each logs as row}
              <tr>
                <td>{row.id}</td>
                <td>{row.plate_no ?? "—"}</td>
                <td>{row.chainage}</td>
                <td>{row.delta_mm}</td>
                <td><span class="tag {row.status === 'pending' ? 'pending' : 'ok'}">{row.status === 'pending' ? '待处理' : '已完成'}</span></td>
                <td>
                  {#if row.verdict}
                    <span class="tag {row.verdict === '合格' ? 'ok' : 'bad'}">{row.verdict}</span>
                  {:else}—{/if}
                </td>
                <td>{row.reason ?? "—"}</td>
              </tr>
            {/each}
          </tbody>
        </table>
      </section>
    {:else}
      <section>
        <h2>绑定示例</h2>
        <p class="note">
          在役铭牌才能报测缝：选择 <span class="example">MP-0001（K12+180）</span> 填收敛值即交得下；
          对已退役的 <span class="example">MP-0002</span> 再交同断面测缝，接口整份退回（409），不留新单；
          MP-0002 退役前的旧测缝单仍留原来的号 MP-0002，旧绑定不可改。
        </p>
      </section>

      <section>
        <h2>在役铭牌（{plates.active.length}）</h2>
        <table>
          <thead>
            <tr><th>铭牌号</th><th>断面</th><th>登记人</th><th>登记时间</th><th>操作</th></tr>
          </thead>
          <tbody>
            {#each plates.active as p}
              <tr>
                <td><b>{p.plate_no}</b></td>
                <td>{p.chainage}</td>
                <td>{p.created_by}</td>
                <td>{fmt(p.created_at)}</td>
                <td>
                  {#if isWriter}
                    <button class="secondary" on:click={() => gotoLogsWith(p.plate_no)}>用此号报测缝</button>
                    <button on:click={() => retirePlate(p)}>退役</button>
                  {:else}
                    <span class="rowline">巡检只读</span>
                  {/if}
                </td>
              </tr>
            {/each}
          </tbody>
        </table>
      </section>

      <section>
        <h2>退役铭牌（{plates.retired.length}）</h2>
        <table>
          <thead>
            <tr><th>铭牌号</th><th>断面</th><th>退役时间</th><th>退役人</th><th>原因</th></tr>
          </thead>
          <tbody>
            {#each plates.retired as p}
              <tr>
                <td><b>{p.plate_no}</b></td>
                <td>{p.chainage}</td>
                <td>{fmt(p.retired_at)}</td>
                <td>{p.retired_by}</td>
                <td>{p.retire_reason ?? "—"}</td>
              </tr>
            {/each}
          </tbody>
        </table>
        <p class="rowline" style="margin-top:0.5rem">退役只移动到本表；旧测缝单仍保留原号绑定，任何人改不了旧绑定，也不能再拿此号交单。</p>
      </section>

      {#if isWriter}
        <section>
          <h2>号段维护（测量员）</h2>
          <label>新铭牌号（形如 MP-0000，范围 MP-0000~MP-9999）</label>
          <input placeholder="MP-0100" bind:value={newPlateNo} autocomplete="off" />
          <label>绑定断面桩号</label>
          <input placeholder="例如 K22+300" bind:value={newChainage} autocomplete="off" />
          <button disabled={loading} on:click={registerPlate}>登记为在役铭牌</button>
        </section>
      {/if}

      <section>
        <h2>铭牌履历（名册改动与绑定均在此留痕，一次写齐）</h2>
        <table>
          <thead>
            <tr><th>时间</th><th>铭牌号</th><th>事项</th><th>说明</th><th>测缝单#</th><th>操作人</th></tr>
          </thead>
          <tbody>
            {#each events as e}
              <tr>
                <td>{fmt(e.created_at)}</td>
                <td>{e.plate_no}</td>
                <td>{kindLabel(e.kind)}</td>
                <td>{e.detail ?? "—"}</td>
                <td>{e.log_id ?? "—"}</td>
                <td>{e.actor}</td>
              </tr>
            {/each}
          </tbody>
        </table>
      </section>
    {/if}
  {/if}
</main>
