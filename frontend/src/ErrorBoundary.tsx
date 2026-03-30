import { Component, type ErrorInfo, type ReactNode } from "react";

type Props = { children: ReactNode };

type State = { error: Error | null };

export class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error("React render error:", error, info.componentStack);
  }

  render() {
    if (this.state.error) {
      return (
        <div
          style={{
            padding: "1.5rem",
            fontFamily: "system-ui, sans-serif",
            maxWidth: "42rem",
          }}
        >
          <h1 style={{ fontSize: "1.1rem", marginBottom: "0.75rem" }}>
            Ошибка интерфейса
          </h1>
          <p style={{ opacity: 0.9, marginBottom: "0.5rem" }}>
            При отрисовке произошла ошибка. Откройте консоль браузера (F12 →
            Console) для подробностей.
          </p>
          <pre
            style={{
              background: "#2a2a2a",
              padding: "0.75rem",
              borderRadius: "8px",
              overflow: "auto",
              fontSize: "0.85rem",
            }}
          >
            {this.state.error.message}
          </pre>
          <button
            type="button"
            style={{ marginTop: "1rem", padding: "0.4rem 0.8rem" }}
            onClick={() => this.setState({ error: null })}
          >
            Попробовать снова
          </button>
        </div>
      );
    }
    return this.props.children;
  }
}
