<script>
  let session = null;
  let view = "desk"; // desk=测缝报送, book=铭牌册专页
  let logs = [];
  let plates = [];
  let loginUser = "surveyor";
  let loginPass = "surv123456";

  // 报送表单
  let plateCode = ""; // 只能点在役号填入；空着才可点
  let boundSection = "";
  let deltaMm = "";

  // 入册表单
  let newCode = "";
  let newSection = "";

  let error = "";
  let notice = "";
  let loading = false;
  let timer;

  $: isWriter = session?.role === "writer";
  $: activePlates = plates.filter((p) => p.status === "active");
  $: retiredPlates = plates.filter((p) => p.status === "retired");

  function headers() {
    return session ? { Authorization: "Bearer " + session.token } : {};
  }

  async function refreshLogs() {
    if (!session) return;
    const res = await fetch("/api/logs", { headers: headers() });
    if (res.status === 401) return logout();
    if (res.ok) logs = await res.json();
  }

  async function refreshPlates() {
    if (!session) return;
    const res = await fetch("/api/plates", { headers: headers() });
    if (res.status === 401) return logout();
    if (res.ok) plates = await res.json();
  }

  async function refreshAll() {
    await Promise.all([refreshLogs(), refreshPlates()]);
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
      await refreshAll();
      timer = setInterval(refreshAll, 2000);
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
    plates = [];
    resetForm();
    localStorage.removeItem("tunnel_session");
  }

  function resetForm() {
    plateCode = "";
    boundSection = "";
    deltaMm = "";
  }

  // 号只能“点在役号、且号栏空着”时填入。
  function pickActive(p) {
    error = "";
    if (plateCode) {
      error = `本单已绑 ${plateCode}，请先清空再改点其它在役号`;
      return;
    }
    plateCode = p.code;
    boundSection = p.section;
  }

  // 点退役号：整份退回——清空整份填报，不留半成品。
  function pickRetired(p) {
    resetForm();
    notice = "";
    error = `铭牌 ${p.code} 已退役，整份退回：该号旧单仍留原来的号，但不能再交新单`;
  }

  function clearBinding() {
    plateCode = "";
    boundSection = "";
    error = "";
  }

  async function submit() {
    error = "";
    notice = "";
    if (!plateCode) {
      error = "没有在役铭牌不许报测缝，请点选在役铭牌号";
      return;
    }
    loading = true;
    try {
      const res = await fetch("/api/logs", {
        method: "POST",
        headers: { "Content-Type": "application/json", ...headers() },
        // 只发号与读数；断面由后端按在册锁定行回填，前端改不动。
        body: JSON.stringify({ plate_code: plateCode, delta_mm: Number(deltaMm) }),
      });
      const data = await res.json();
      if (!res.ok) {
        // 含提交瞬间被退役：整份退回。
        resetForm();
        error = data.detail || "提交失败";
        return;
      }
      notice = `已交：号 ${data.plate_code} 绑定 ${data.section}，进入待认领`;
      resetForm();
      await refreshAll();
    } catch {
      error = "提交时网络异常";
    } finally {
      loading = false;
    }
  }

  async function registerPlate() {
    error = "";
    notice = "";
    const code = newCode.trim();
    const section = newSection.trim();
    if (!code || !section) {
      error = "铭牌号与绑定断面都不能为空";
      return;
    }
    loading = true;
    try {
      const res = await fetch("/api/plates", {
        method: "POST",
        headers: { "Content-Type": "application/json", ...headers() },
        body: JSON.stringify({ code, section }),
      });
      const data = await res.json();
      if (!res.ok) {
        error = data.detail || "入册失败";
        return;
      }
      newCode = "";
      newSection = "";
      notice = `号 ${code} 已入册（名册与履历已一次写齐）`;
      await refreshPlates();
    } catch {
      error = "入册时网络异常";
    } finally {
      loading = false;
    }
  }

  async function retire(p) {
    error = "";
    notice = "";
    loading = true;
    try {
      const res = await fetch(`/api/plates/${encodeURIComponent(p.code)}/retire`, {
        method: "POST",
        headers: headers(),
      });
      const data = await res.json();
      if (!res.ok) {
        error = data.detail || "退役失败";
        return;
      }
      // 若正在报送的单绑的是它，按“整份退回”处理。
      if (plateCode === p.code) resetForm();
      notice = `铭牌 ${p.code} 已退役；旧单仍留原来的号，不得改旧绑定`;
      await refreshAll();
    } catch {
      error = "退役时网络异常";
    } finally {
      loading = false;
    }
  }

  const raw = localStorage.getItem("tunnel_session");
  if (raw) {
    try {
      session = JSON.parse(raw);
      refreshAll();
      timer = setInterval(refreshAll, 2000);
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
  .topbar {
    display: flex; align-items: center; justify-content: space-between;
    border-bottom: 1px solid #44403c; padding-bottom: 0.75rem; margin-bottom: 1rem;
  }
  h1 { color: #fbbf24; margin: 0; font-size: 1.3rem; }
  nav { display: flex; gap: 0.5rem; }
  .sub { color: #a8a29e; margin-bottom: 1.25rem; }
  section {
    background: #292524; border: 1px solid #44403c; border-radius: 8px;
    padding: 1rem 1.25rem; margin-bottom: 1rem;
  }
  h2 { font-size: 1.05rem; margin: 0 0 0.75rem; color: #fde68a; }
  label { display: block; font-size: 0.85rem; color: #d6d3d1; margin-bottom: 0.25rem; }
  input {
    width: 100%; box-sizing: border-box; padding: 0.5rem 0.65rem; border-radius: 6px;
    border: 1px solid #57534e; background: #0c0a09; color: #fafaf9; margin-bottom: 0.75rem;
  }
  button {
    cursor: pointer; padding: 0.45rem 0.9rem; border: none; border-radius: 6px;
    background: #d97706; color: #fff; font-weight: 600;
  }
  button:disabled { opacity: 0.5; cursor: not-allowed; }
  button.secondary { background: #57534e; }
  button.nav { background: #44403c; }
  button.nav.active { background: #d97706; }
  button.chip { background: #14532d; color: #86efac; font-weight: 500; margin: 0 0.4rem 0.4rem 0; }
  button.chip.dead { background: #7f1d1d; color: #fca5a5; }
  .err { color: #fb7185; }
  .ok-msg { color: #86efac; }
  table { width: 100%; border-collapse: collapse; font-size: 0.9rem; }
  th, td { text-align: left; padding: 0.45rem; border-bottom: 1px solid #44403c; vertical-align: top; }
  .tag { padding: 0.1rem 0.4rem; border-radius: 4px; font-size: 0.8rem; }
  .ok { background: #14532d; color: #86efac; }
  .bad { background: #7f1d1d; color: #fca5a5; }
  .pending { background: #713f12; color: #fde68a; }
  .live { background: #14532d; color: #86efac; }
  .retired { background: #57534e; color: #d6d3d1; }
  .grid2 { display: grid; grid-template-columns: 1fr 1fr; gap: 1rem; }
  .boundbox { background: #0c0a09; border: 1px dashed #a16207; border-radius: 6px; padding: 0.6rem 0.75rem; margin-bottom: 0.75rem; }
  .example { background: #1c1410; border: 1px solid #a16207; border-radius: 6px; padding: 0.6rem 0.75rem; font-size: 0.88rem; color: #fde68a; }
  .muted { color: #a8a29e; font-size: 0.85rem; }
  @media (max-width: 760px) { .grid2 { grid-template-columns: 1fr; } }
</style>

<main>
  {#if !session}
    <h1>隧道收敛测缝台</h1>
    <p class="sub">测量员凭在役铭牌报测缝，接口进程内线程认领后出结论。登录框已预填可写账号 surveyor / surv123456。</p>
    <section>
      <label>用户名</label>
      <input bind:value={loginUser} autocomplete="off" />
      <label>密码</label>
      <input type="password" bind:value={loginPass} autocomplete="off" />
      <button disabled={loading} on:click={login}>登录</button>
      {#if error}<p class="err">{error}</p>{/if}
    </section>
  {:else}
    <div class="topbar">
      <h1>隧道收敛测缝台</h1>
      <nav>
        <!-- 铭牌册专页从页眉点进去 -->
        <button class="nav {view === 'desk' ? 'active' : ''}" on:click={() => (view = 'desk')}>测缝报送</button>
        <button class="nav {view === 'book' ? 'active' : ''}" on:click={() => (view = 'book')}>铭牌册</button>
        <button class="secondary" on:click={logout}>退出</button>
      </nav>
    </div>
    <p class="sub">
      已登录：{session.username}（{isWriter ? '测量员·可报送/维护号段' : '巡检岗·只读名册'}）
      <button class="secondary" style="margin-left:0.5rem" disabled={loading} on:click={refreshAll}>刷新</button>
    </p>
    {#if error}<p class="err">⛔ {error}</p>{/if}
    {#if notice}<p class="ok-msg">✅ {notice}</p>{/if}

    {#if view === 'desk'}
      {#if isWriter}
        <section>
          <h2>第一步 · 点在役铭牌绑定（号栏空着才填；点退役号整份退回）</h2>
          {#if plateCode}
            <div class="boundbox">
              本单已绑：号 <b>{plateCode}</b> → 断面 <b>{boundSection}</b>
              <button class="secondary" style="margin-left:0.6rem" on:click={clearBinding}>清空重选</button>
            </div>
          {:else}
            <div class="boundbox muted">尚未绑定在役铭牌，号栏为空——请在下方点一个在役号。</div>
          {/if}

          <label>在役铭牌（点号填入，自动绑其断面）</label>
          <div>
            {#each activePlates as p}
              <button class="chip" on:click={() => pickActive(p)}>{p.code}｜{p.section}</button>
            {:else}
              <span class="muted">暂无在役铭牌</span>
            {/each}
          </div>

          <label style="margin-top:0.6rem">退役铭牌（点了=整份退回，不能再交新单；旧单仍留原来的号）</label>
          <div>
            {#each retiredPlates as p}
              <button class="chip dead" on:click={() => pickRetired(p)}>{p.code}｜{p.section}｜已退役</button>
            {:else}
              <span class="muted">暂无退役铭牌</span>
            {/each}
          </div>
        </section>

        <section>
          <h2>第二步 · 填收敛并提交</h2>
          <label>收敛（毫米，可正可负）</label>
          <input type="number" step="0.1" bind:value={deltaMm} />
          <button disabled={loading || !plateCode} on:click={submit}>
            提交（号 {plateCode || '未绑'} · 进入待认领）
          </button>
          {#if !plateCode}<p class="muted">没有在役铭牌不许报测缝。</p>{/if}
        </section>
      {:else}
        <section><p class="muted">巡检岗可读取名册与报送记录，但不能改册、不能报送。</p></section>
      {/if}

      <section>
        <h2>测缝单（含历史旧单，号随旧单永久保留）</h2>
        <table>
          <thead>
            <tr><th>编号</th><th>铭牌号</th><th>绑定断面</th><th>收敛mm</th><th>状态</th><th>结论</th><th>说明</th></tr>
          </thead>
          <tbody>
            {#each logs as row}
              <tr>
                <td>{row.id}</td>
                <td>{row.plate_code}</td>
                <td>{row.section}</td>
                <td>{row.delta_mm}</td>
                <td><span class="tag {row.status === 'pending' ? 'pending' : 'ok'}">{row.status === 'pending' ? '待处理' : '已完成'}</span></td>
                <td>
                  {#if row.verdict}<span class="tag {row.verdict === '合格' ? 'ok' : 'bad'}">{row.verdict}</span>{:else}—{/if}
                </td>
                <td>{row.reason ?? '—'}</td>
              </tr>
            {/each}
          </tbody>
        </table>
      </section>
    {:else}
      <!-- 铭牌册专页：在役、退役两张表 + 绑定示例 -->
      <section>
        <h2>绑定示例</h2>
        <div class="example">
          号 <b>J-12180</b> 绑 <b>K12+180 甲断面</b>：报送时点在役号 J-12180（号栏空着才填入），
          断面以后端在册记录为准，交单即“号甲绑甲断面，交得下”。
          该号一旦退役，旧单仍是 J-12180，旧绑定改不了；同号再交新单会被整份退回。
        </div>
      </section>

      <div class="grid2">
        <section>
          <h2>在役铭牌（{activePlates.length}）</h2>
          <table>
            <thead><tr><th>铭牌号</th><th>绑定断面</th><th>{isWriter ? '操作' : '状态'}</th></tr></thead>
            <tbody>
              {#each activePlates as p}
                <tr>
                  <td><span class="tag live">在役</span> {p.code}</td>
                  <td>{p.section}</td>
                  <td>
                    {#if isWriter}
                      <button class="chip dead" on:click={() => retire(p)}>退役</button>
                    {:else}
                      <span class="muted">只读</span>
                    {/if}
                  </td>
                </tr>
              {:else}
                <tr><td colspan="3" class="muted">暂无在役铭牌</td></tr>
              {/each}
            </tbody>
          </table>
        </section>

        <section>
          <h2>退役铭牌（{retiredPlates.length}）</h2>
          <table>
            <thead><tr><th>铭牌号</th><th>绑定断面</th><th>状态</th></tr></thead>
            <tbody>
              {#each retiredPlates as p}
                <tr>
                  <td><span class="tag retired">退役</span> {p.code}</td>
                  <td>{p.section}</td>
                  <td class="muted">旧单留号，不可再绑</td>
                </tr>
              {:else}
                <tr><td colspan="3" class="muted">暂无退役铭牌</td></tr>
              {/each}
            </tbody>
          </table>
        </section>
      </div>

      {#if isWriter}
        <section>
          <h2>维护号段 · 新号入册（名册与履历一次写齐）</h2>
          <label>铭牌号</label>
          <input placeholder="例如 J-21030" bind:value={newCode} autocomplete="off" />
          <label>绑定断面</label>
          <input placeholder="例如 K21+030 甲断面" bind:value={newSection} autocomplete="off" />
          <button disabled={loading} on:click={registerPlate}>入册</button>
        </section>
      {:else}
        <section><p class="muted">巡检岗：能读名册，不能改册。</p></section>
      {/if}
    {/if}
  {/if}
</main>
