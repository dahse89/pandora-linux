# Pandora Linux: pinned, root-managed Oh My Zsh; user state stays in HOME.
export ZSH=/usr/share/pandora-linux/oh-my-zsh/42a4ccb1b14dbeffe81259105a5243b4f4cb618e
export ZSH_CUSTOM="${XDG_CONFIG_HOME:-$HOME/.config}/oh-my-zsh/custom"
export ZSH_CACHE_DIR="${XDG_CACHE_HOME:-$HOME/.cache}/oh-my-zsh"
mkdir -p -- "$ZSH_CUSTOM" "$ZSH_CACHE_DIR"
ZSH_COMPDUMP="$ZSH_CACHE_DIR/.zcompdump-${HOST}-${ZSH_VERSION}"
zstyle ':omz:update' mode disabled
ZSH_THEME=robbyrussell
plugins=(git)
source "$ZSH/oh-my-zsh.sh"
