import { NavLink } from "react-router-dom";
import { Activity, Camera, Cpu, FlaskConical, ShieldCheck, Video } from "lucide-react";
import { cn } from "@/lib/utils";

const links = [
  { to: "/ui/live", label: "Live", icon: Video },
  { to: "/ui/cameras", label: "Cameras", icon: Camera },
  { to: "/ui/model", label: "Model", icon: Cpu },
  { to: "/ui/runs", label: "Runs", icon: FlaskConical },
  { to: "/ui/events", label: "Events", icon: Activity },
];

export function NavBar() {
  return (
    <header className="border-b border-border bg-card px-4 py-2 flex items-center gap-6 flex-wrap sticky top-0 z-20">
      <div className="flex items-center gap-2 mr-2">
        <ShieldCheck className="h-5 w-5 text-primary" />
        <span className="font-semibold text-foreground text-sm tracking-tight">
          Physical AI Safety
        </span>
        <span className="hidden sm:inline text-xs text-muted-foreground">operator console</span>
      </div>
      <nav className="flex items-center gap-1 flex-wrap">
        {links.map(({ to, label, icon: Icon }) => (
          <NavLink
            key={to}
            to={to}
            className={({ isActive }) =>
              cn(
                "flex items-center gap-1.5 px-3 py-1.5 rounded-md text-sm transition-colors",
                isActive
                  ? "bg-primary/15 text-primary font-medium"
                  : "text-muted-foreground hover:text-foreground hover:bg-secondary"
              )
            }
          >
            <Icon className="h-3.5 w-3.5" />
            {label}
          </NavLink>
        ))}
      </nav>
    </header>
  );
}
