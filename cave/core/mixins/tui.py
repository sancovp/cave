"""TUIMixin - Text User Interface for CAVEAgent.

Display dialogs, messages, and popups in tmux sessions.
"""
import subprocess
import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class TUIMixin:
    """Mixin for TUI displays in tmux sessions.
    
    Provides:
        - display_message: Status bar message
        - display_popup: Popup window (tmux 3.2+)
        - display_pane: Text in a pane
        - display_dialog: Interactive dialog via gum/dialog
        - display_menu: Selection menu
        - display_confirm: Yes/No confirmation
        - display_input: Text input dialog
        - display_spinner: Loading spinner
    """
    
    def _get_tmux_session(self) -> str:
        """Get the current tmux session name."""
        if hasattr(self, 'config') and hasattr(self.config, 'main_agent_config'):
            return self.config.main_agent_config.tmux_session
        return "main"
    
    # === TMUX NATIVE ===
    
    def display_message(
        self, 
        message: str, 
        duration_ms: int = 3000,
        session: Optional[str] = None
    ) -> Dict[str, Any]:
        """Display a message in tmux status bar.
        
        Args:
            message: Message to display
            duration_ms: Duration in milliseconds
            session: Target session (default: main agent session)
        """
        session = session or self._get_tmux_session()
        try:
            # Set display time
            subprocess.run([
                "tmux", "set-option", "-t", session,
                "display-time", str(duration_ms)
            ], capture_output=True)
            
            # Display message
            result = subprocess.run([
                "tmux", "display-message", "-t", session, message
            ], capture_output=True, text=True)
            
            return {"success": result.returncode == 0, "message": message}
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    def display_popup(
        self,
        content: str,
        title: Optional[str] = None,
        width: str = "80%",
        height: str = "80%",
        session: Optional[str] = None,
        style: Optional[str] = None
    ) -> Dict[str, Any]:
        """Display a popup window in tmux (requires tmux 3.2+).
        
        Args:
            content: Text or command to display
            title: Popup title
            width: Width (e.g., "80%", "60")
            height: Height (e.g., "80%", "20")
            session: Target session
            style: Border style
        """
        session = session or self._get_tmux_session()
        
        cmd = ["tmux", "display-popup", "-t", session]
        
        if title:
            cmd.extend(["-T", title])
        cmd.extend(["-w", width, "-h", height])
        if style:
            cmd.extend(["-S", style])
        
        # Use echo to display content, or run as command
        cmd.extend(["-E", f"echo '{content}'; read -n1 -p 'Press any key...'"])
        
        try:
            result = subprocess.run(cmd, capture_output=True, text=True)
            return {"success": result.returncode == 0}
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    def display_pane(
        self,
        content: str,
        session: Optional[str] = None,
        pane: str = "0"
    ) -> Dict[str, Any]:
        """Send content to a tmux pane (displays in session).
        
        Args:
            content: Text to display
            session: Target session
            pane: Pane index
        """
        session = session or self._get_tmux_session()
        target = f"{session}:{pane}"
        
        try:
            # Clear the pane first (optional)
            # subprocess.run(["tmux", "send-keys", "-t", target, "clear", "Enter"])
            
            # Echo the content
            result = subprocess.run([
                "tmux", "send-keys", "-t", target,
                f"echo '{content}'", "Enter"
            ], capture_output=True, text=True)
            
            return {"success": result.returncode == 0}
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    # === GUM DIALOGS (if installed) ===
    
    def _gum_available(self) -> bool:
        """Check if gum is available."""
        result = subprocess.run(["which", "gum"], capture_output=True)
        return result.returncode == 0
    
    def display_confirm(
        self,
        prompt: str,
        affirmative: str = "Yes",
        negative: str = "No",
        session: Optional[str] = None
    ) -> Dict[str, Any]:
        """Display a confirmation dialog.
        
        Returns result.confirmed = True if user selected affirmative.
        """
        session = session or self._get_tmux_session()
        
        if self._gum_available():
            cmd = [
                "tmux", "send-keys", "-t", session,
                f"gum confirm '{prompt}' --affirmative='{affirmative}' --negative='{negative}' && echo 'YES' || echo 'NO'",
                "Enter"
            ]
        else:
            # Fallback to read
            cmd = [
                "tmux", "send-keys", "-t", session,
                f"read -p '{prompt} (y/n): ' ans; [ \"$ans\" = \"y\" ] && echo 'YES' || echo 'NO'",
                "Enter"
            ]
        
        try:
            result = subprocess.run(cmd, capture_output=True, text=True)
            return {"success": result.returncode == 0, "prompt": prompt}
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    def display_input(
        self,
        prompt: str,
        placeholder: str = "",
        session: Optional[str] = None
    ) -> Dict[str, Any]:
        """Display an input dialog.
        
        Note: This sends the command to tmux. Getting the result
        requires capturing pane output after.
        """
        session = session or self._get_tmux_session()
        
        if self._gum_available():
            cmd = [
                "tmux", "send-keys", "-t", session,
                f"gum input --placeholder '{placeholder}' --header '{prompt}'",
                "Enter"
            ]
        else:
            cmd = [
                "tmux", "send-keys", "-t", session,
                f"read -p '{prompt}: ' input; echo $input",
                "Enter"
            ]
        
        try:
            result = subprocess.run(cmd, capture_output=True, text=True)
            return {"success": result.returncode == 0, "prompt": prompt}
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    def display_menu(
        self,
        title: str,
        options: List[str],
        session: Optional[str] = None
    ) -> Dict[str, Any]:
        """Display a selection menu.
        
        Note: This sends the command to tmux. Getting the selection
        requires capturing pane output after.
        """
        session = session or self._get_tmux_session()
        options_str = " ".join(f'"{opt}"' for opt in options)
        
        if self._gum_available():
            cmd = [
                "tmux", "send-keys", "-t", session,
                f"gum choose {options_str} --header '{title}'",
                "Enter"
            ]
        else:
            # Fallback to select
            select_cmd = f"echo '{title}'; select opt in {options_str}; do echo $opt; break; done"
            cmd = [
                "tmux", "send-keys", "-t", session,
                select_cmd,
                "Enter"
            ]
        
        try:
            result = subprocess.run(cmd, capture_output=True, text=True)
            return {"success": result.returncode == 0, "title": title, "options": options}
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    def display_spinner(
        self,
        title: str,
        command: str,
        session: Optional[str] = None
    ) -> Dict[str, Any]:
        """Display a spinner while running a command.
        
        Args:
            title: Spinner message
            command: Command to run while spinner shows
            session: Target session
        """
        session = session or self._get_tmux_session()
        
        if self._gum_available():
            cmd = [
                "tmux", "send-keys", "-t", session,
                f"gum spin --title '{title}' -- {command}",
                "Enter"
            ]
        else:
            # Just run the command with echo
            cmd = [
                "tmux", "send-keys", "-t", session,
                f"echo '{title}...'; {command}",
                "Enter"
            ]
        
        try:
            result = subprocess.run(cmd, capture_output=True, text=True)
            return {"success": result.returncode == 0, "title": title}
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    # === STYLED TEXT ===
    
    def display_styled(
        self,
        text: str,
        style: str = "bold",
        session: Optional[str] = None
    ) -> Dict[str, Any]:
        """Display styled text using gum or ANSI codes.
        
        Styles: bold, italic, strikethrough, underline, faint
        Also supports colors: --foreground "#FF0000"
        """
        session = session or self._get_tmux_session()
        
        if self._gum_available():
            cmd = [
                "tmux", "send-keys", "-t", session,
                f"gum style --{style} '{text}'",
                "Enter"
            ]
        else:
            # ANSI fallback
            style_map = {
                "bold": "\033[1m",
                "italic": "\033[3m",
                "underline": "\033[4m",
                "faint": "\033[2m",
            }
            code = style_map.get(style, "")
            reset = "\033[0m"
            cmd = [
                "tmux", "send-keys", "-t", session,
                f"echo -e '{code}{text}{reset}'",
                "Enter"
            ]
        
        try:
            result = subprocess.run(cmd, capture_output=True, text=True)
            return {"success": result.returncode == 0}
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    def display_box(
        self,
        content: str,
        title: Optional[str] = None,
        border: str = "rounded",
        session: Optional[str] = None
    ) -> Dict[str, Any]:
        """Display text in a box (requires gum).
        
        Border styles: rounded, double, thick, hidden, normal
        """
        session = session or self._get_tmux_session()
        
        if not self._gum_available():
            # Fallback: just echo with a header
            lines = [
                f"┌─ {title or 'Info'} ─┐",
                content,
                "└────────────────┘"
            ]
            cmd = [
                "tmux", "send-keys", "-t", session,
                "; ".join(f"echo '{line}'" for line in lines),
                "Enter"
            ]
        else:
            gum_cmd = f"echo '{content}' | gum style --border {border}"
            if title:
                gum_cmd += f" --border-title '{title}'"
            cmd = [
                "tmux", "send-keys", "-t", session,
                gum_cmd,
                "Enter"
            ]
        
        try:
            result = subprocess.run(cmd, capture_output=True, text=True)
            return {"success": result.returncode == 0}
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    # === STATUS HELPERS ===
    
    def notify(
        self,
        title: str,
        message: str,
        level: str = "info",
        session: Optional[str] = None
    ) -> Dict[str, Any]:
        """Display a notification with icon.
        
        Levels: info, success, warning, error
        """
        icons = {
            "info": "ℹ️",
            "success": "✅",
            "warning": "⚠️",
            "error": "❌"
        }
        icon = icons.get(level, "•")
        full_message = f"{icon} {title}: {message}"
        
        return self.display_message(full_message, session=session)
