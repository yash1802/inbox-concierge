import { Navigate, Route, Routes } from "react-router-dom";
import { InboxPage } from "./pages/InboxPage";
import { LoginPage } from "./pages/LoginPage";

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<InboxPage />} />
      <Route path="/login" element={<LoginPage />} />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
