import { Link, Route, Routes } from "react-router-dom";

import {
  AuthProvider,
  LoginPage,
  ProtectedRoute,
} from "./auth/AuthContext";
import { BriefWorkspace } from "./briefs/BriefWorkspace";
import { JobStatusPage } from "./jobs/JobStatusPage";
import { ReportHistoryPage } from "./reports/ReportHistoryPage";
import { ReportReaderPage } from "./reports/ReportReaderPage";

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
        登录并进入报告工作台
      </Link>
    </main>
  );
}

export default function App() {
  return (
    <AuthProvider>
      <Routes>
        <Route path="/" element={<HomePage />} />
        <Route path="/login" element={<LoginPage />} />
        <Route
          path="/reports"
          element={
            <ProtectedRoute>
              <ReportHistoryPage />
            </ProtectedRoute>
          }
        />
        <Route
          path="/reports/:reportId"
          element={
            <ProtectedRoute>
              <ReportReaderPage />
            </ProtectedRoute>
          }
        />
        <Route
          path="/briefs/new"
          element={
            <ProtectedRoute>
              <BriefWorkspace />
            </ProtectedRoute>
          }
        />
        <Route
          path="/jobs/:jobId"
          element={
            <ProtectedRoute>
              <JobStatusPage />
            </ProtectedRoute>
          }
        />
      </Routes>
    </AuthProvider>
  );
}
