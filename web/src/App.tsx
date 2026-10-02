import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { NavBar } from "@/components/nav-bar";
import { LivePage } from "@/pages/live";
import { CamerasPage } from "@/pages/cameras";
import { ModelPage } from "@/pages/model";
import { RunsPage } from "@/pages/runs";
import { EventsPage } from "@/pages/events";

export function App() {
  return (
    <BrowserRouter>
      <div className="min-h-full flex flex-col">
        <NavBar />
        <main className="flex-1 px-4 py-4 max-w-[1600px] w-full mx-auto">
          <Routes>
            <Route path="/" element={<Navigate to="/ui/live" replace />} />
            <Route path="/ui" element={<Navigate to="/ui/live" replace />} />
            <Route path="/ui/live" element={<LivePage />} />
            <Route path="/ui/cameras" element={<CamerasPage />} />
            <Route path="/ui/model" element={<ModelPage />} />
            <Route path="/ui/runs" element={<RunsPage />} />
            <Route path="/ui/events" element={<EventsPage />} />
            <Route path="*" element={<Navigate to="/ui/live" replace />} />
          </Routes>
        </main>
      </div>
    </BrowserRouter>
  );
}
