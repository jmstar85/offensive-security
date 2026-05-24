import { Moon, Sun } from "lucide-react";
import { cn } from "../lib/utils";
import { useTheme } from "../lib/theme";

interface ThemeToggleProps {
  collapsed?: boolean;
  className?: string;
}

export function ThemeToggle({ collapsed = false, className }: ThemeToggleProps) {
  const { theme, toggleTheme } = useTheme();
  const isDark = theme === "dark";

  return (
    <button
      type="button"
      onClick={toggleTheme}
      aria-label={`Switch to ${isDark ? "light" : "dark"} mode`}
      className={cn(
        "w-full flex items-center gap-3 px-3 py-2.5 rounded-md text-sm text-muted-foreground hover:bg-accent hover:text-foreground transition-colors",
        className
      )}
    >
      {isDark ? (
        <Sun className="w-4 h-4 flex-shrink-0" />
      ) : (
        <Moon className="w-4 h-4 flex-shrink-0" />
      )}
      {!collapsed && <span>{isDark ? "Light mode" : "Dark mode"}</span>}
    </button>
  );
}
