import { BrowserRouter, Routes, Route } from "react-router-dom";
import "@/App.css";
import GuestPage from "@/pages/GuestPage";
import AdminPage from "@/pages/AdminPage";

function App() {
  return (
    <div className="App">
      <BrowserRouter>
        <Routes>
          <Route path="/" element={<GuestPage />} />
          <Route path="/admin" element={<AdminPage />} />
        </Routes>
      </BrowserRouter>
    </div>
  );
}

export default App;
