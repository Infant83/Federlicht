```mermaid
flowchart TD
    A[Start: report.py CLI] --> B[Resolve run/archive paths]
    B --> C[Load prompt/template/spec]
    C --> D[Infer policy<br/>depth/style/wants_web]
    D --> E[Build source index + triage]
    E --> F[Scout]
    F --> G{Clarifier enabled?}
    G -->|Yes| H[Clarifier Q/A]
    G -->|No| I[Alignment (scout)?]
    H --> I
    I --> J{Template adjust?}
    J -->|Yes| K[Template adjuster]
    J -->|No| L[Planner]
    K --> L
    L --> M{Web search?}
    M -->|Yes| N[Web query + supporting]
    M -->|No| O[Evidence?]
    N --> O
    O -->|Yes| P[Evidence notes]
    P --> Q[Plan check update]
    Q --> R[Claim map + Gap report]
    O -->|No| S[Writer]
    R --> S
    S --> T[Structural repair]
    T --> U{Quality iterations?}
    U -->|Yes| V[Critic/Reviser loop]
    V --> W[Evaluate + Pairwise]
    W --> X[Writer finalizer]
    U -->|No| Y[Final structural repair]
    X --> Y
    Y --> Z[Alignment (final)]
    Z --> AA[Render output + write files]
