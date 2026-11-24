import { useEffect, useState } from 'react'
import { createRoot } from 'react-dom/client'
import './style.css'

type Project = { id: string, name: string, organization: string, role: string }
type Job = { id: string, state: string, plugin: string, attempt: number, result: unknown }
type Workflow = { id: string, state: string, nodes: Record<string, { state: string }> }
type Dataset = { id: string, name: string }
type Funding = {
  budget: { limit: number, spent: number },
  requests: { id: string, purpose: string, amount: number, state: string }[],
}
const sections = ['Overview', 'Jobs', 'Workflows', 'Datasets', 'Funding', 'Audit', 'System health'] as const
type Section = typeof sections[number]

function Workspace() {
  const [token, setToken] = useState('')
  const [projects, setProjects] = useState<Project[]>([])
  const [projectId, setProjectId] = useState('')
  const [section, setSection] = useState<Section>('Overview')
  const [jobs, setJobs] = useState<Job[]>([])
  const [workflows, setWorkflows] = useState<Workflow[]>([])
  const [datasets, setDatasets] = useState<Dataset[]>([])
  const [funding, setFunding] = useState<Funding | null>(null)
  const [details, setDetails] = useState<unknown>(null)
  const [status, setStatus] = useState('')
  const [loading, setLoading] = useState(false)
  const [observations, setObservations] = useState('1, 2, 3, 4')
  const project = projects.find((item) => item.id === projectId)

  async function api<T>(path: string, init?: RequestInit, authorization = token): Promise<T> {
    const headers = new Headers(init?.headers)
    if (authorization) headers.set('Authorization', 'Basic ' + authorization)
    const response = await fetch('/api' + path, { ...init, headers })
    const payload = await response.json()
    if (!response.ok) throw new Error(typeof payload.detail === 'string' ? payload.detail : 'Request failed (' + response.status + ')')
    return payload as T
  }

  async function refresh() {
    setStatus('')
    setDetails(null)
    setLoading(true)
    try {
      if (section === 'System health') {
        const readiness = await api('/readyz')
        setDetails({ readiness, execution: await api('/metrics').catch(() => null) })
        return
      }
      if (!projectId) return
      const base = '/projects/' + projectId
      if (section === 'Overview' || section === 'Jobs') setJobs(await api<Job[]>(base + '/jobs'))
      if (section === 'Overview' || section === 'Workflows') setWorkflows(await api<Workflow[]>(base + '/workflows'))
      if (section === 'Datasets') setDatasets(await api<Dataset[]>(base + '/datasets'))
      if (section === 'Funding') setFunding(await api<Funding>(base + '/funding'))
      if (section === 'Audit') setDetails(await api(base + '/audit'))
    } catch (error) {
      setStatus(String(error))
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    setJobs([])
    setWorkflows([])
    setDatasets([])
    setFunding(null)
    if (token) void refresh()
  }, [token, projectId, section])

  async function run(action: () => Promise<void>) {
    try { setStatus(''); await action() }
    catch (error) { setStatus(String(error)) }
  }

  async function download(path: string, filename: string) {
    const response = await fetch('/api' + path, { headers: { Authorization: 'Basic ' + token } })
    if (!response.ok) throw new Error('Download unavailable (' + response.status + ')')
    const url = URL.createObjectURL(await response.blob())
    const link = document.createElement('a')
    link.href = url
    link.download = filename
    link.click()
    setTimeout(() => URL.revokeObjectURL(url), 1000)
  }

  async function submit(workflow: boolean) {
    const values = observations.split(',').map((part) => part.trim())
    if (values.some((value) => !/^-?\d+$/.test(value))) throw new Error('Enter comma-separated integers')
    const node = { plugin: 'summary@1', parameters: { observations: values.map(Number) } }
    const body = workflow ? { nodes: {
      baseline: { ...node, depends_on: [] },
      replicate: { ...node, depends_on: [] },
      report: { ...node, depends_on: ['baseline', 'replicate'] },
    } } : node
    await api('/projects/' + projectId + (workflow ? '/workflows' : '/jobs'), {
      method: 'POST', body: JSON.stringify(body),
      headers: { 'Content-Type': 'application/json', 'Idempotency-Key': crypto.randomUUID() },
    })
    await refresh()
  }

  return <div className="shell">
    <aside><div className="brand"><span>R</span> ResearchHub</div>
      {token && <nav aria-label="Workspace">{sections.map((item) =>
        <button className={item === section ? 'selected' : ''} key={item} onClick={() => setSection(item)}>{item}</button>
      )}</nav>}
    </aside>
    <main>
      <header><div><p className="eyebrow">{project?.organization ?? 'Research workspace'}</p>
        <h1>{token ? section : 'Sign in'}</h1></div>
        {token && <button onClick={() => { setToken(''); setProjectId(''); setProjects([]); setStatus(''); setSection('Overview') }}>Sign out</button>}
      </header>
      {status && <p role="alert" className="status">{status}</p>}
      {!token ? <form className="panel sign-in" onSubmit={(event) => {
        event.preventDefault()
        const form = new FormData(event.currentTarget)
        void run(async () => {
          const authorization = btoa(String(form.get('user')) + ':' + String(form.get('password')))
          const available = await api<Project[]>('/projects', undefined, authorization)
          setProjects(available); setProjectId(available[0]?.id ?? ''); setToken(authorization)
        })
      }}>
        <label>Username<input name="user" required autoComplete="username" /></label>
        <label>Password<input name="password" type="password" required autoComplete="current-password" /></label>
        <button className="primary">Sign in</button>
      </form> : <>
        <div className="toolbar">
          <label>Project <select value={projectId} onChange={(event) => setProjectId(event.target.value)}>
            {projects.map((item) => <option value={item.id} key={item.id}>{item.name}</option>)}
          </select></label>
          {project && <span className="badge">{project.role}</span>}
          <button onClick={() => void refresh()} disabled={loading}>Refresh</button>
        </div>
        {loading && <p role="status">Loading workspace data…</p>}
        {section === 'Overview' && <div className="cards">
          <article className="panel"><span>Recent jobs</span><strong>{jobs.length}</strong></article>
          <article className="panel"><span>Queued or retrying</span><strong>{jobs.filter((job) => ['QUEUED','RETRYING'].includes(job.state)).length}</strong></article>
          <article className="panel"><span>Running workflows</span><strong>{workflows.filter((workflow) => workflow.state === 'RUNNING').length}</strong></article>
        </div>}
        {(section === 'Jobs' || section === 'Workflows') && projectId && <div className="panel action">
          <label>Observations<input value={observations} onChange={(event) => setObservations(event.target.value)} /></label>
          <button className="primary" onClick={() => void run(() => submit(section === 'Workflows'))}>
            {section === 'Jobs' ? 'Submit summary job' : 'Run summary template'}
          </button>
        </div>}
        {section === 'Jobs' && <div className="panel table-wrap"><table><thead><tr><th scope="col">Plugin</th><th scope="col">Status</th><th scope="col">Attempt</th><th scope="col">Actions</th></tr></thead>
          <tbody>{jobs.map((job) => <tr key={job.id}><td>{job.plugin}</td><td><span className="badge">{job.state}</span></td><td>{job.attempt}</td>
            <td><button onClick={() => void run(async () => setDetails({ result: job.result, events: await api('/projects/' + projectId + '/jobs/' + job.id + '/events') }))}>Details</button>
            {job.state === 'SUCCEEDED' && (['manifest', 'json', 'csv'] as const).map((kind) =>
              <button key={kind} onClick={() => void run(() => download('/projects/' + projectId + '/jobs/' + job.id + '/download/' + kind, kind === 'manifest' ? 'manifest.json' : 'result.' + kind))}>
                {kind === 'manifest' ? 'Manifest' : kind.toUpperCase()}
              </button>)}
            {['QUEUED', 'RUNNING', 'RETRYING'].includes(job.state) && <button onClick={() => void run(async () => {
              await api('/projects/' + projectId + '/jobs/' + job.id + '/cancel', { method: 'POST' }); await refresh()
            })}>Cancel</button>}</td></tr>)}</tbody></table>
          {jobs.length === 0 && <p>No jobs submitted in this project.</p>}</div>}
        {section === 'Workflows' && workflows.map((workflow) => <article className="panel workflow" key={workflow.id}>
          <h2>Summary workflow <span className="badge">{workflow.state}</span></h2>
          <ol>{Object.entries(workflow.nodes).map(([name, node]) => <li key={name}><b>{name}</b><span>{node.state}</span></li>)}</ol>
        </article>)}
        {section === 'Datasets' && <section className="panel"><ul>{datasets.map((dataset) => <li key={dataset.id}>
          <button onClick={() => void run(async () => setDetails(await api('/projects/' + projectId + '/datasets/' + dataset.id + '/versions')))}>{dataset.name}</button>
        </li>)}</ul>{datasets.length === 0 && <p>No datasets registered in this project.</p>}</section>}
        {section === 'Funding' && funding && <section className="panel">
          <p>Available balance <strong>{funding.budget.limit - funding.budget.spent}</strong> minor currency units</p>
          {project?.role !== 'finance' && <form className="action" onSubmit={(event) => {
            event.preventDefault()
            const form = new FormData(event.currentTarget)
            void run(async () => {
              await api('/projects/' + projectId + '/funding', {
                method: 'POST', body: JSON.stringify({ amount: Number(form.get('amount')), purpose: form.get('purpose') }),
                headers: { 'Content-Type': 'application/json', 'Idempotency-Key': crypto.randomUUID() },
              })
              await refresh()
            })
          }}>
            <label>Amount<input name="amount" type="number" min="1" max="1000000000000" required /></label>
            <label>Purpose<input name="purpose" maxLength={300} required /></label>
            <button className="primary">Request funds</button>
          </form>}
          <ul>{funding.requests.map((request) => <li key={request.id}>
            {request.purpose} · {request.amount} · {request.state}
            {request.state === 'PENDING' && ['finance', 'platform_admin'].includes(project?.role ?? '') &&
              [true, false].map((approve) => <button key={String(approve)} onClick={() => void run(async () => {
                await api('/projects/' + projectId + '/funding/' + request.id + '/decision', {
                  method: 'POST', body: JSON.stringify({ approve }), headers: { 'Content-Type': 'application/json' },
                })
                await refresh()
              })}>{approve ? 'Approve' : 'Reject'}</button>)}
          </li>)}</ul>
          {funding.requests.length === 0 && <p>No funding requests.</p>}
        </section>}
        {details !== null && <pre className="panel">{JSON.stringify(details, null, 2)}</pre>}
      </>}
    </main>
  </div>
}

createRoot(document.getElementById('root')!).render(<Workspace />)

