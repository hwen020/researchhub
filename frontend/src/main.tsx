import { useEffect, useRef, useState } from 'react'
import { createRoot } from 'react-dom/client'
import './style.css'

type Project = { id: string, name: string, organization: string, role: string }
type Job = { id: string, state: string, plugin: string, attempt: number, result: unknown, wait_reason?: string }
type Workflow = { id: string, state: string, version_id?: string, parent_id?: string,
  dependencies: Record<string, string[]>, conditions: Record<string, { mode: string }>, nodes: Record<string, { state: string, reused_from?: string }> }
type Quota = { max_concurrent: number, max_queued: number, quota_cpu: number, quota_memory: number, storage_quota_bytes: number }
type Resources = { quota: Quota, usage: { active: number, queued: number, cpu_units: number, memory_units: number }, storage_bytes: number }
type ProjectNotice = { id: string, sequence: number, message: string, kind: string, created_at: number, read: boolean }
type Artifact = { id: string, kind: string, version: number, state: string, size: number, checksum: string }
type Worker = { id: string, capabilities: string[], cpu_units: number, memory_units: number }
type Template = { id: string, name: string }
type WorkflowVersion = { id: string, version: number, checksum: string }
type Schedule = { id: string, next_at: number | null, zone: string }
type Dataset = { id: string, name: string }
type DatasetVersion = { id: string, version: number, checksum: string, size: number, state?: string }
type Organization = { id: string, name: string }
type Member = { username: string, role: 'pi' | 'researcher' | 'finance' }
type Funding = {
  budget: { limit: number, spent: number },
  requests: { id: string, purpose: string, amount: number, state: string }[],
}
const sections = ['Overview', 'Jobs', 'Workflows', 'Resources', 'Datasets', 'Artifacts', 'Notifications', 'Funding', 'Members', 'Audit', 'System health', 'Administration'] as const
type Section = typeof sections[number]

function Workspace() {
  const [token, setToken] = useState('')
  const [projects, setProjects] = useState<Project[]>([])
  const [projectId, setProjectId] = useState('')
  const [section, setSection] = useState<Section>('Overview')
  const [jobs, setJobs] = useState<Job[]>([])
  const [workflows, setWorkflows] = useState<Workflow[]>([])
  const [resources, setResources] = useState<Resources | null>(null)
  const [artifactList, setArtifactList] = useState<Artifact[]>([])
  const [notices, setNotices] = useState<ProjectNotice[]>([])
  const [noticeError, setNoticeError] = useState('')
  const [workerList, setWorkerList] = useState<Worker[]>([])
  const [templates, setTemplates] = useState<Template[]>([])
  const [selectedTemplate, setSelectedTemplate] = useState('')
  const [versions, setVersions] = useState<WorkflowVersion[]>([])
  const [scheduleVersion, setScheduleVersion] = useState('')
  const [schedules, setSchedules] = useState<Schedule[]>([])
  const [isDemo, setIsDemo] = useState(false)
  const [datasets, setDatasets] = useState<Dataset[]>([])
  const [selectedDataset, setSelectedDataset] = useState('')
  const [datasetVersions, setDatasetVersions] = useState<DatasetVersion[]>([])
  const [funding, setFunding] = useState<Funding | null>(null)
  const [members, setMembers] = useState<Member[]>([])
  const [memberRoles, setMemberRoles] = useState<Record<string, Member['role']>>({})
  const [organizations, setOrganizations] = useState<Organization[]>([])
  const [details, setDetails] = useState<unknown>(null)
  const [status, setStatus] = useState('')
  const [loading, setLoading] = useState(false)
  const [observations, setObservations] = useState('1, 2, 3, 4')
  const [isAdmin, setIsAdmin] = useState(false)
  const [pendingAuthorization, setPendingAuthorization] = useState('')
  const [pendingUsername, setPendingUsername] = useState('')
  const [temporaryPassword, setTemporaryPassword] = useState('')
  const refreshSequence = useRef(0)
  const project = projects.find((item) => item.id === projectId)
  const projectPath = '/projects/' + projectId
  const canCompute = !isDemo && ['pi', 'researcher', 'platform_admin'].includes(project?.role ?? '')

  async function api<T>(path: string, init?: RequestInit, authorization = token): Promise<T> {
    const headers = new Headers(init?.headers)
    if (authorization) headers.set('Authorization', 'Basic ' + authorization)
    const response = await fetch('/api' + path, { ...init, headers })
    const payload = await response.json()
    if (!response.ok) throw new Error(typeof payload.detail === 'string' ? payload.detail : 'Request failed (' + response.status + ')')
    return payload as T
  }

  async function refresh() {
    const refreshId = ++refreshSequence.current
    setStatus('')
    setDetails(null)
    setLoading(true)
    try {
      if (section === 'System health') {
        const readiness = await api('/readyz')
        setDetails({ readiness, execution: await api('/metrics').catch(() => null) })
        return
      }
      if (section === 'Administration') {
        setOrganizations(await api<Organization[]>('/admin/organizations'))
        setDetails(await api('/admin/audit'))
        return
      }
      if (!projectId) return
      const base = '/projects/' + projectId
      if (section === 'Overview' || section === 'Jobs') {
        const currentJobs = await api<Job[]>(base + '/jobs')
        if (refreshId === refreshSequence.current) setJobs(currentJobs)
      }
      if (section === 'Overview' || section === 'Workflows') {
        const currentRuns = await api<Workflow[]>(base + '/workflows')
        if (refreshId === refreshSequence.current) setWorkflows(currentRuns)
      }
      if (section === 'Workflows' && !isDemo) {
        const [currentTemplates, currentSchedules, currentDatasets] = await Promise.all([
          api<Template[]>(base + '/workflow-templates'), api<Schedule[]>(base + '/workflow-schedules'),
          api<Dataset[]>(base + '/datasets'),
        ])
        if (refreshId === refreshSequence.current) {
          setTemplates(currentTemplates)
          setSchedules(currentSchedules)
          setDatasets(currentDatasets)
          if (selectedTemplate) setVersions(await api<WorkflowVersion[]>(base + '/workflow-templates/' + selectedTemplate + '/versions'))
        }
      }
      if (section === 'Resources') {
        const [snapshot, online] = await Promise.all([
          api<Resources>(base + '/resources'), isAdmin ? api<Worker[]>('/admin/workers') : Promise.resolve([]),
        ])
        if (refreshId === refreshSequence.current) {
          setResources(snapshot)
          setWorkerList(online)
        }
      }
      if (section === 'Artifacts') {
        const list = await api<Artifact[]>(base + '/artifacts')
        if (refreshId === refreshSequence.current) setArtifactList(list)
      }
      if (section === 'Datasets') {
        const currentDatasets = await api<Dataset[]>(base + '/datasets')
        if (refreshId === refreshSequence.current) setDatasets(currentDatasets)
      }
      if (section === 'Funding') setFunding(await api<Funding>(base + '/funding'))
      if (section === 'Members') {
        const currentMembers = await api<Member[]>(base + '/members')
        setMembers(currentMembers)
        setMemberRoles(Object.fromEntries(currentMembers.map((member) => [member.username, member.role])))
      }
      if (section === 'Audit') setDetails(await api(base + '/audit'))
    } catch (error) {
      if (refreshId === refreshSequence.current) setStatus(String(error))
    } finally {
      if (refreshId === refreshSequence.current) setLoading(false)
    }
  }

  useEffect(() => {
    setJobs([])
    setWorkflows([])
    setDatasets([])
    setResources(null)
    setArtifactList([])
    setFunding(null)
    if (token) void refresh()
  }, [token, projectId, section])

  useEffect(() => {
    setSelectedTemplate('')
    setScheduleVersion('')
    setSelectedDataset('')
    setDatasetVersions([])
    setTemplates([])
    setVersions([])
    setSchedules([])
  }, [projectId])

  useEffect(() => {
    if (!token || !projectId || section !== 'Notifications' || isDemo) return
    let active = true
    let cursor = 0
    let timer: ReturnType<typeof setTimeout>
    setNotices([])
    setNoticeError('')
    async function poll() {
      let delay = 3000
      try {
        const update = await api<{ items: ProjectNotice[], cursor: number }>(projectPath + '/notifications?after=' + cursor)
        if (!active) return
        cursor = update.cursor
        if (update.items.length) setNotices((current) => [...update.items.slice().reverse(), ...current].slice(0, 200))
        setNoticeError('')
        if (update.items.length === 100) delay = 0
      } catch (error) {
        if (active) setNoticeError(String(error))
      } finally {
        if (active) timer = setTimeout(poll, delay)
      }
    }
    void poll()
    return () => { active = false; clearTimeout(timer) }
  }, [token, projectId, section, isDemo])

  async function jsonAction(path: string, body: unknown, method = 'POST') {
    return api(path, { method, body: JSON.stringify(body), headers: { 'Content-Type': 'application/json' } })
  }

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
      {token && <nav aria-label="Workspace">{sections.filter((item) =>
        (!isDemo || ['Overview', 'Jobs', 'Workflows', 'Datasets', 'System health'].includes(item)) &&
        (item !== 'Administration' || isAdmin) &&
        (item !== 'Members' || ['pi', 'platform_admin'].includes(project?.role ?? ''))
      ).map((item) =>
        <button className={item === section ? 'selected' : ''} key={item} onClick={() => setSection(item)}>{item}</button>
      )}</nav>}
    </aside>
    <main>
      <header><div><p className="eyebrow">{project?.organization ?? 'Research workspace'}</p>
        <h1>{token ? section : 'Sign in'}</h1></div>
        {token && <button onClick={() => {
          setToken(''); setProjectId(''); setProjects([]); setStatus(''); setSection('Overview')
          setIsAdmin(false); setIsDemo(false); setTemporaryPassword(''); setDetails(null)
        }}>Sign out</button>}
      </header>
      {status && <p role="alert" className="status">{status}</p>}
      {!token && pendingAuthorization ? <form className="panel sign-in" onSubmit={(event) => {
        event.preventDefault()
        const password = String(new FormData(event.currentTarget).get('password'))
        void run(async () => {
          await api('/auth/password', {
            method: 'POST', body: JSON.stringify({ password }),
            headers: { 'Content-Type': 'application/json' },
          }, pendingAuthorization)
          const authorization = btoa(pendingUsername + ':' + password)
          const available = await api<Project[]>('/projects', undefined, authorization)
          const authStatus = await api<{ platform_admin: boolean }>('/auth/status', undefined, authorization)
          setProjects(available); setProjectId(available[0]?.id ?? ''); setIsAdmin(authStatus.platform_admin)
          setPendingAuthorization(''); setPendingUsername(''); setToken(authorization)
        })
      }}>
        <p>A temporary password must be changed before continuing.</p>
        <label>New password<input name="password" type="password" minLength={12} maxLength={256} required autoComplete="new-password" /></label>
        <button className="primary">Change password</button>
      </form> : !token ? <form className="panel sign-in" onSubmit={(event) => {
        event.preventDefault()
        const form = new FormData(event.currentTarget)
        void run(async () => {
          const authorization = btoa(String(form.get('user')) + ':' + String(form.get('password')))
          const authStatus = await api<{ platform_admin: boolean, must_change_password: boolean, demo_mode: boolean }>('/auth/status', undefined, authorization)
          setIsAdmin(authStatus.platform_admin)
          setIsDemo(authStatus.demo_mode)
          if (authStatus.must_change_password) {
            setPendingAuthorization(authorization); setPendingUsername(String(form.get('user')))
            setStatus('A temporary password must be changed before continuing.')
            return
          }
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
        {isDemo && section === 'Overview' && <p className="panel">Read-only demonstration. Open Workflows to inspect the fixed synthetic genomics run.</p>}
        {(section === 'Jobs' || section === 'Workflows') && canCompute && <div className="panel action">
          <label>Observations<input value={observations} onChange={(event) => setObservations(event.target.value)} /></label>
          <button className="primary" onClick={() => void run(() => submit(section === 'Workflows'))}>
            {section === 'Jobs' ? 'Submit summary job' : 'Run summary template'}
          </button>
        </div>}
        {section === 'Jobs' && <div className="panel table-wrap"><table><thead><tr><th scope="col">Plugin</th><th scope="col">Status</th><th scope="col">Attempt</th><th scope="col">Actions</th></tr></thead>
          <tbody>{jobs.map((job) => <tr key={job.id}><td>{job.plugin}</td><td><span className="badge">{job.state}</span>{job.wait_reason && <small className="wait-reason">{job.wait_reason.replaceAll('_', ' ')}</small>}</td><td>{job.attempt}</td>
            <td><button onClick={() => void run(async () => setDetails({ result: job.result, events: await api('/projects/' + projectId + '/jobs/' + job.id + '/events') }))}>Details</button>
            {job.state === 'SUCCEEDED' && (['manifest', 'json', 'csv', ...(job.plugin === 'mobility-report@1' ? ['geojson'] : [])]).map((kind) =>
              <button key={kind} onClick={() => void run(() => download('/projects/' + projectId + '/jobs/' + job.id + '/download/' + kind, kind === 'manifest' ? 'manifest.json' : 'result.' + kind))}>
                {kind === 'manifest' ? 'Manifest' : kind.toUpperCase()}
              </button>)}
            {canCompute && ['QUEUED', 'RUNNING', 'RETRYING'].includes(job.state) && <button onClick={() => void run(async () => {
              await api('/projects/' + projectId + '/jobs/' + job.id + '/cancel', { method: 'POST' }); await refresh()
            })}>Cancel</button>}</td></tr>)}</tbody></table>
          {jobs.length === 0 && <p>No jobs submitted in this project.</p>}</div>}
        {section === 'Resources' && resources && <>
          <section className="panel">
            <h2>Project resource usage</h2>
            <dl className="usage-grid">
              <div><dt>Concurrent attempts</dt><dd>{resources.usage.active} / {resources.quota.max_concurrent}</dd></div>
              <div><dt>Outstanding jobs</dt><dd>{resources.usage.active + resources.usage.queued} / {resources.quota.max_queued}</dd></div>
              <div><dt>Logical CPU units</dt><dd>{resources.usage.cpu_units} / {resources.quota.quota_cpu}</dd></div>
              <div><dt>Logical memory units</dt><dd>{resources.usage.memory_units} / {resources.quota.quota_memory}</dd></div>
              <div><dt>Artifact storage bytes</dt><dd>{resources.storage_bytes} / {resources.quota.storage_quota_bytes}</dd></div>
            </dl>
            {isAdmin && <form key={JSON.stringify(resources.quota)} className="quota-form" onSubmit={(event) => {
              event.preventDefault()
              const form = new FormData(event.currentTarget)
              void run(async () => {
                await jsonAction(projectPath + '/resources', Object.fromEntries(Object.keys(resources.quota).map((key) =>
                  [key, Number(form.get(key))])), 'PUT')
                await refresh()
              })
            }}>
              {([['max_concurrent', 'Concurrent limit'], ['max_queued', 'Outstanding limit'],
                ['quota_cpu', 'Logical CPU limit'], ['quota_memory', 'Logical memory limit'],
                ['storage_quota_bytes', 'Storage limit (bytes)']] as const).map(([key, label]) =>
                <label key={key}>{label}<input name={key} type="number" min="1"
                  defaultValue={resources.quota[key]} required /></label>)}
              <button className="primary">Save quota</button>
            </form>}
          </section>
          {isAdmin && <section className="panel">
            <h2>Online workers</h2>
            {workerList.length === 0 && <p>No workers reported a recent heartbeat.</p>}
            <ul>{workerList.map((worker) => <li key={worker.id}>{worker.capabilities.join(', ')} · {worker.cpu_units} CPU / {worker.memory_units} memory units</li>)}</ul>
          </section>}
        </>}
        {section === 'Workflows' && <>
          {canCompute && <section className="panel">
            <h2>Research workflows</h2>
            {datasets.length === 0 ? <p>Register and upload a dataset version to run an analysis.</p> :
              <form className="quota-form" onSubmit={(event) => {
                event.preventDefault()
                const form = new FormData(event.currentTarget)
                void run(async () => {
                  await jsonAction(projectPath + '/research-workflows', {
                    discipline: form.get('discipline'), timezone: form.get('timezone'),
                    dataset: { id: form.get('dataset'), version: Number(form.get('version')) },
                  })
                  await refresh()
                })
              }}>
                <label>Discipline<select name="discipline"><option value="genomics">Genomics</option>
                  <option value="mobility">Wearable mobility</option></select></label>
                <label>Dataset<select name="dataset" required>{datasets.map((dataset) =>
                  <option key={dataset.id} value={dataset.id}>{dataset.name}</option>)}</select></label>
                <label>Dataset version<input name="version" type="number" min="1" defaultValue="1" required /></label>
                <label>Study timezone<input name="timezone" defaultValue="UTC" required /></label>
                <button className="primary">Start research workflow</button>
              </form>}
          </section>}
          {!isDemo && <section className="panel">
            <h2>Workflow versions and schedules</h2>
            {templates.length === 0 ? <p>No versioned templates in this project.</p> :
              <label>Template <select value={selectedTemplate} onChange={(event) => {
                const id = event.target.value
                setSelectedTemplate(id); setScheduleVersion(''); setVersions([])
                if (id) void run(async () => setVersions(await api<WorkflowVersion[]>(projectPath + '/workflow-templates/' + id + '/versions')))
              }}><option value="">Select a template</option>
                {templates.map((template) => <option key={template.id} value={template.id}>{template.name}</option>)}
              </select></label>}
            <ul>{versions.map((version) => <li key={version.id}>Version {version.version} <code>{version.checksum.slice(0, 12)}</code>
              {canCompute && <button onClick={() => void run(async () => {
                await jsonAction(projectPath + '/workflow-versions/' + version.id + '/runs', {}); await refresh()
              })}>Run with defaults</button>}</li>)}</ul>
            {canCompute && <details>
              <summary>{selectedTemplate ? 'Publish a new version' : 'Create workflow template'}</summary>
              <form className="workspace-form" onSubmit={(event) => {
                event.preventDefault()
                const form = event.currentTarget
                const data = new FormData(form)
                void run(async () => {
                  const definition = JSON.parse(String(data.get('definition')))
                  const path = projectPath + '/workflow-templates'
                  await jsonAction(selectedTemplate ? path + '/' + selectedTemplate + '/versions' : path,
                    selectedTemplate ? definition : { ...definition, name: data.get('name') })
                  form.reset()
                  await refresh()
                })
              }}>
                {!selectedTemplate && <label>Template name<input name="name" maxLength={120} required /></label>}
                <label>Workflow definition JSON<textarea name="definition" rows={6} required defaultValue={JSON.stringify({
                  nodes: { summary: { plugin: 'summary@1', parameters: { observations: { $parameter: 'values' } } } },
                  defaults: { values: [1, 2, 3] },
                }, null, 2)} /></label>
                <button className="primary">Publish template version</button>
              </form>
            </details>}
            {canCompute && versions.length > 0 && <details>
              <summary>Schedule a workflow version</summary>
              <form className="quota-form" onSubmit={(event) => {
                event.preventDefault()
                const form = new FormData(event.currentTarget)
                void run(async () => {
                  const interval = form.get('interval')
                  await jsonAction(projectPath + '/workflow-versions/' + scheduleVersion + '/schedules', {
                    start_at: form.get('when'), zone: form.get('zone'),
                    interval_seconds: interval ? Number(interval) : null,
                  })
                  await refresh()
                })
              }}>
                <label>Workflow version<select value={scheduleVersion} required onChange={(event) =>
                  setScheduleVersion(event.target.value)}><option value="">Select a version</option>
                  {versions.map((version) => <option value={version.id} key={version.id}>Version {version.version}</option>)}</select></label>
                <label>Start time with offset<input name="when" placeholder="2026-12-01T09:00:00+00:00" required /></label>
                <label>Timezone<input name="zone" defaultValue="UTC" required /></label>
                <label>Repeat interval in seconds<input name="interval" type="number" min="60" /></label>
                <button className="primary">Schedule run</button>
              </form>
            </details>}
            {schedules.length === 0 ? <p>No scheduled workflows.</p> :
              <ul>{schedules.map((schedule) => <li key={schedule.id}>{schedule.next_at === null ? 'Completed' :
                new Intl.DateTimeFormat(undefined, { dateStyle: 'medium', timeStyle: 'short', timeZone: schedule.zone }).format(schedule.next_at)} · {schedule.zone}
                {canCompute && schedule.next_at !== null && <button onClick={() => void run(async () => {
                  await api(projectPath + '/workflow-schedules/' + schedule.id, { method: 'DELETE' })
                  await refresh()
                })}>Stop schedule</button>}</li>)}</ul>}
          </section>}
          {workflows.length > 1 && <form className="panel quota-form" onSubmit={(event) => {
            event.preventDefault()
            const form = new FormData(event.currentTarget)
            void run(async () => {
              setDetails(await api(projectPath + '/workflows/' + form.get('left') + '/compare/' + form.get('right')))
            })
          }}>
            {([['left', 'First run'], ['right', 'Second run']] as const).map(([key, label]) => <label key={key}>{label}
              <select name={key} required><option value="">Choose a run</option>{workflows.map((workflow) =>
                <option value={workflow.id} key={workflow.id}>{workflow.state} {workflow.id.slice(0, 8)}</option>)}</select>
            </label>)}
            <button>Compare runs</button>
          </form>}
          {workflows.length === 0 && !loading && <p>No workflow runs in this project.</p>}
          {workflows.map((workflow) => {
            const path = projectPath + '/workflows/' + workflow.id
            const canRerun = canCompute && ['FAILED', 'CANCELLED'].includes(workflow.state)
            return <article className="panel workflow" key={workflow.id} data-run-id={workflow.id}>
              <h2>{isDemo ? 'Synthetic genomics workflow' : 'Workflow run'} <span className="badge">{workflow.state}</span></h2>
              <div className="action">
                <button onClick={() => void run(async () => setDetails(await api(path + '/provenance')))}>Provenance</button>
                <button onClick={() => void run(() => download(path + '/provenance?download=true', 'provenance.json'))}>Download provenance</button>
                {workflow.parent_id && <button onClick={() => void run(async () =>
                  setDetails(await api(path + '/compare/' + workflow.parent_id)))}>Compare with parent</button>}
                {canRerun && <button onClick={() => void run(async () => {
                  await jsonAction(path + '/rerun', {}); await refresh()
                })}>Rerun workflow</button>}
                {canCompute && workflow.state === 'RUNNING' && <button onClick={() => void run(async () => {
                  await api(path + '/cancel', { method: 'POST' }); await refresh()
                })}>Cancel workflow</button>}
              </div>
              <ol>{Object.entries(workflow.nodes).map(([name, node]) => <li key={name}>
                <b>{name}</b><span>{node.state}{node.reused_from && ' · reused'}</span>
                {workflow.dependencies?.[name]?.length > 0 && <small>After {workflow.dependencies[name].join(', ')}
                  {workflow.conditions?.[name] && ' · ' + workflow.conditions[name].mode.replaceAll('_', ' ')}</small>}
                {canRerun && ['FAILED', 'CANCELLED'].includes(node.state) && <button onClick={() => void run(async () => {
                  await jsonAction(path + '/rerun', { failed_node: name }); await refresh()
                })}>Rerun from {name}</button>}
              </li>)}</ol>
            </article>
          })}
        </>}
        {section === 'Artifacts' && <section className="panel table-wrap">
          <h2>Scientific artifact registry</h2>
          {artifactList.length === 0 ? <p>No managed artifacts in this project.</p> :
            <table><thead><tr><th scope="col">Artifact</th><th scope="col">Status</th><th scope="col">Bytes</th><th scope="col">Actions</th></tr></thead>
              <tbody>{artifactList.map((artifact) => <tr key={artifact.id}>
                <td>{artifact.kind === 'DATASET' ? 'Dataset v' + artifact.version : 'Result snapshot'}
                  <small className="wait-reason" title={artifact.checksum}>{artifact.checksum.slice(0, 12)}</small></td>
                <td>{artifact.state}</td><td>{artifact.size}</td>
                <td>{artifact.state === 'AVAILABLE' && <button onClick={() => void run(() => download(
                  projectPath + '/artifacts/' + artifact.id + '/download', artifact.kind === 'DATASET' ? 'dataset.csv' : 'result.json',
                ))}>Download</button>}</td>
              </tr>)}</tbody></table>}
        </section>}
        {section === 'Datasets' && <section className="panel">
          {canCompute && <form className="quota-form" onSubmit={(event) => {
            event.preventDefault()
            const form = event.currentTarget
            const name = new FormData(form).get('name')
            void run(async () => {
              await jsonAction(projectPath + '/datasets', { name })
              form.reset()
              await refresh()
            })
          }}>
            <label>Dataset name<input name="name" maxLength={200} required /></label>
            <button className="primary">Register dataset</button>
          </form>}
          <ul>{datasets.map((dataset) => <li key={dataset.id}>
            <button onClick={() => void run(async () => {
              const items = await api<DatasetVersion[]>(projectPath + '/datasets/' + dataset.id + '/versions')
              setSelectedDataset(dataset.id); setDatasetVersions(items)
            })}>{dataset.name}</button>
          </li>)}</ul>
          {datasets.length === 0 && <p>No datasets registered in this project.</p>}
          {selectedDataset && <>
            <h2>Dataset versions</h2>
            {canCompute && <form className="quota-form" onSubmit={(event) => {
              event.preventDefault()
              const form = event.currentTarget
              const file = new FormData(form).get('csv')
              if (!(file instanceof File) || !file.size) return
              const path = projectPath + '/datasets/' + selectedDataset + '/versions'
              void run(async () => {
                await api(path, { method: 'POST', body: file,
                  headers: { 'Content-Type': 'text/csv', 'Idempotency-Key': crypto.randomUUID() } })
                form.reset()
                setDatasetVersions(await api<DatasetVersion[]>(path))
              })
            }}>
              <label>CSV file<input name="csv" type="file" accept=".csv,text/csv" required /></label>
              <button className="primary">Upload new version</button>
            </form>}
            <ul>{datasetVersions.map((version) => <li key={version.id}>
              Version {version.version} · {version.size} bytes · {version.state ?? 'AVAILABLE'}
              {(!version.state || version.state === 'AVAILABLE') && <button onClick={() => void run(() => download(
                projectPath + '/datasets/' + selectedDataset + '/versions/' + version.version, 'dataset.csv',
              ))}>Download dataset</button>}
            </li>)}</ul>
          </>}
        </section>}
        {section === 'Notifications' && <section className="panel">
          {['pi', 'platform_admin'].includes(project?.role ?? '') && <form className="quota-form" onSubmit={(event) => {
            event.preventDefault()
            const form = event.currentTarget
            const message = new FormData(form).get('message')
            void run(async () => {
              await jsonAction(projectPath + '/notifications/announcements', { message })
              form.reset()
            })
          }}>
            <label>Project announcement<input name="message" maxLength={500} required /></label>
            <button className="primary">Post announcement</button>
          </form>}
          {noticeError && <p role="alert" className="status">{noticeError}</p>}
          {notices.length === 0 && <p>No project notifications.</p>}
          <ul className="notice-list">{notices.map((notice) => <li key={notice.id}>
            <div><strong>{notice.message}</strong> <span className="badge">{notice.read ? 'Read' : 'Unread'}</span></div>
            <small>{new Date(notice.created_at).toLocaleString()}</small>
            <button onClick={() => void run(async () => {
              await jsonAction(projectPath + '/notifications/' + notice.id + '/read', { read: !notice.read }, 'PUT')
              setNotices((items) => items.map((item) => item.id === notice.id ? { ...item, read: !notice.read } : item))
            })}>{notice.read ? 'Mark unread' : 'Mark read'}</button>
          </li>)}</ul>
        </section>}
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
        {section === 'Members' && projectId && <section className="panel">
          <h2>Project members</h2>
          <form className="action" onSubmit={(event) => {
            event.preventDefault()
            const form = new FormData(event.currentTarget)
            void run(async () => {
              await api('/projects/' + projectId + '/members', {
                method: 'POST', body: JSON.stringify({ username: form.get('username'), role: form.get('role') }),
                headers: { 'Content-Type': 'application/json' },
              })
              await refresh()
            })
          }}>
            <label>Username<input name="username" minLength={3} maxLength={100} required /></label>
            <label>Role<select name="role"><option value="researcher">researcher</option><option value="finance">finance</option>
              {isAdmin && <option value="pi">pi</option>}
            </select></label>
            <button className="primary">Add member</button>
          </form>
          <ul>{members.map((member) => <li key={member.username}>
            <span>{member.username}</span>
            <select aria-label={'Role for ' + member.username} value={memberRoles[member.username] ?? member.role}
              onChange={(event) => setMemberRoles({ ...memberRoles, [member.username]: event.target.value as Member['role'] })}>
              <option value="researcher">researcher</option><option value="finance">finance</option>
              {isAdmin && <option value="pi">pi</option>}
            </select>
            <button onClick={() => void run(async () => {
              await api('/projects/' + projectId + '/members/' + encodeURIComponent(member.username), {
                method: 'PATCH', body: JSON.stringify({ role: memberRoles[member.username] ?? member.role }),
                headers: { 'Content-Type': 'application/json' },
              })
              await refresh()
            })}>Save role</button>
            <button onClick={() => void run(async () => {
              await api('/projects/' + projectId + '/members/' + encodeURIComponent(member.username), { method: 'DELETE' })
              await refresh()
            })}>Remove</button>
          </li>)}</ul>
        </section>}
        {section === 'Administration' && isAdmin && <>
          <section className="panel">
            <h2>Create project</h2>
            <form className="action" onSubmit={(event) => {
              event.preventDefault()
              const form = new FormData(event.currentTarget)
              void run(async () => {
                const created = await api<{ id: string }>('/admin/projects', {
                  method: 'POST', body: JSON.stringify({
                    organization_id: form.get('organization'), name: form.get('name'), budget_limit: Number(form.get('budget')),
                  }), headers: { 'Content-Type': 'application/json' },
                })
                const available = await api<Project[]>('/projects')
                setProjects(available); setProjectId(created.id); setSection('Overview')
              })
            }}>
              <label>Organization<select name="organization" required>{organizations.map((organization) =>
                <option key={organization.id} value={organization.id}>{organization.name}</option>)}</select></label>
              <label>Project<input name="name" minLength={1} maxLength={200} required /></label>
              <label>Budget limit<input name="budget" type="number" min="0" max="1000000000000" required /></label>
              <button className="primary">Create project</button>
            </form>
          </section>
          <section className="panel">
            <h2>Create account</h2>
            <form className="action" onSubmit={(event) => {
              event.preventDefault()
              const formElement = event.currentTarget
              const form = new FormData(formElement)
              void run(async () => {
                const created = await api<{ username: string, temporary_password: string }>('/admin/accounts', {
                  method: 'POST', body: JSON.stringify({ username: form.get('username') }),
                  headers: { 'Content-Type': 'application/json' },
                })
                setTemporaryPassword(created.username + ': ' + created.temporary_password)
                formElement.reset()
              })
            }}>
              <label>Username<input name="username" minLength={3} maxLength={100} pattern="[A-Za-z0-9._-]+" required /></label>
              <button className="primary">Create account</button>
            </form>
            {temporaryPassword && <p role="status">One-time password: <code>{temporaryPassword}</code>
              <button onClick={() => setTemporaryPassword('')}>Dismiss</button>
            </p>}
          </section>
        </>}
        {details !== null && <pre className="panel">{JSON.stringify(details, null, 2)}</pre>}
      </>}
    </main>
  </div>
}

createRoot(document.getElementById('root')!).render(<Workspace />)

