# Voice Assistant Architecture

```mermaid
graph TB
    subgraph "Client Browser"
        A[Web Interface] --> B[Audio Capture]
        B --> C[WebSocket Connection]
        C --> D[Real-time Audio Stream]
    end

    subgraph "Django Server"
        E[WebSocket Consumer] --> F[Voice Assistant Core]

        subgraph "Voice Processing Pipeline"
            F --> G[Wake Word Detection]
            G --> H[Speech to Text]
            H --> I[LLM Processing]
            I --> J[Text to Speech]
        end

        subgraph "Latency Tracking"
            K[Latency Monitor] --> L[(Metrics Storage)]
        end

        J --> M[Audio Response]
    end

    subgraph "External Services"
        N[Google STT API]
        O[OpenRouter LLM]
        P[gTTS Service]
    end

    H --> N
    I --> O
    J --> P

    M --> C
    L --> Q[Latency Dashboard]

    subgraph "Hardware"
        R[Microphone]
        S[Speakers]
    end

    B --> R
    S -.-> M

    style A fill:#e1f5fe
    style F fill:#fff3e0
    style K fill:#f3e5f5
    style Q fill:#e8f5e8