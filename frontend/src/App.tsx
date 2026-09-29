import { Link, Route, Routes } from "react-router-dom";

function HomePage() {
  return (
    <main className="shell">
      <p className="eyebrow">OPERATIONS INTELLIGENCE</p>
      <h1>专业运营策略 Agent</h1>
      <p className="lead">
        用可信案例、场景适配和质量审查，把运营想法转化为可执行方案。
      </p>
      <aside className="notice" aria-label="数据使用提醒">
        请勿输入个人隐私、客户明细或公司机密；可以使用汇总指标和匿名描述。
      </aside>
      <Link className="primary-link" to="/reports">
        查看报告工作台
      </Link>
    </main>
  );
}

function ReportsPage() {
  return (
    <main className="shell">
      <p className="eyebrow">REPORT WORKSPACE</p>
      <h1>报告工作台</h1>
      <p className="lead">报告任务、历史版本和证据将在这里展示。</p>
      <Link className="secondary-link" to="/">
        返回首页
      </Link>
    </main>
  );
}

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<HomePage />} />
      <Route path="/reports" element={<ReportsPage />} />
    </Routes>
  );
}
