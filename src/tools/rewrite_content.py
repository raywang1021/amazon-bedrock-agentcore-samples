from strands import tool

REWRITE_SYSTEM_PROMPT = """You are a Generative Engine Optimization Expert. Directly rewrite the user's input content following these GEO best practices:

1. **Structure & Clarity**: Use clear headings (H2/H3), short paragraphs, and bullet points. Lead with a concise key takeaway or summary.

2. **Q&A Format**: Where appropriate, restructure content into question-and-answer pairs that generative engines can easily extract and cite.

3. **Data & Citations**: Strengthen claims with specific statistics, data points, and cited sources. Add inline references (e.g., "According to [Source], ...").

4. **E-E-A-T Signals**: Include author credentials, organization context, and transparent sourcing to demonstrate Experience, Expertise, Authoritativeness, and Trustworthiness.

5. **Structured Data Hints**: Suggest applicable schema types (Article, FAQ, HowTo, Organization) and include topic clustering keywords.

6. **Concise Key Takeaways**: Add a "Key Takeaways" section at the top summarizing the main points in 3-5 bullet points.

7. **AI-Friendly Formatting**: Write in a factual, neutral tone. Avoid filler. Every sentence should carry information value.

Output the fully rewritten content. Do not explain what you changed — just output the optimized version."""


@tool
def rewrite_content_for_geo(content: str) -> str:
    """Rewrite and optimize content for Generative Engine Optimization (GEO).

    Takes raw content and rewrites it following GEO best practices to maximize
    visibility, inclusion, and citation in AI-generated responses. Applies clear
    structure, data enrichment, E-E-A-T signals, and Q&A formatting.

    Args:
        content: The raw content text to be rewritten and optimized for GEO.
    """
    from model.load import load_model

    model = load_model()

    from strands import Agent

    rewriter = Agent(
        model=model,
        system_prompt=REWRITE_SYSTEM_PROMPT,
        tools=[],
    )

    result = rewriter(content)
    return f"=== REWRITTEN CONTENT START ===\n{str(result)}\n=== REWRITTEN CONTENT END ==="
