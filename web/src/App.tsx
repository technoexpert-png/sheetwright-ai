import { Navigate, Route, Routes } from "react-router-dom";
import { AppLayout } from "./components/AppLayout";
import { UploadPage } from "./pages/UploadPage";
import { ProcessingPage } from "./pages/ProcessingPage";
import { ReviewPage } from "./pages/ReviewPage";
import { HistoryPage } from "./pages/HistoryPage";
import { SchemasPage } from "./pages/SchemasPage";
import { SchemaEditorPage } from "./pages/SchemaEditorPage";
import { LoginPage } from "./pages/LoginPage";
import { SignupPage } from "./pages/SignupPage";
import { NotFoundPage } from "./pages/NotFoundPage";

export default function App() {
  return (
    <Routes>
      <Route element={<AppLayout />}>
        <Route path="/" element={<UploadPage />} />
        <Route path="/u/:id" element={<ProcessingPage />} />
        <Route path="/u/:id/review" element={<ReviewPage />} />
        <Route path="/uploads" element={<HistoryPage />} />
        <Route path="/schemas" element={<SchemasPage />} />
        {/* Static "new" outranks the dynamic ":id" in React Router's ranking,
            so the editor's two entry points cannot collide. */}
        <Route path="/schemas/new" element={<SchemaEditorPage />} />
        <Route path="/schemas/:id" element={<SchemaEditorPage />} />
        <Route path="/login" element={<LoginPage />} />
        <Route path="/signup" element={<SignupPage />} />
        <Route path="/index.html" element={<Navigate to="/" replace />} />
        <Route path="*" element={<NotFoundPage />} />
      </Route>
    </Routes>
  );
}
