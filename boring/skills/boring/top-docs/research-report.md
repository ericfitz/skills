# What Makes a Written Work Boring

A research report, taxonomy, and rubric sketch for an AI skill that evaluates technical business writing for "boringness" and proposes targeted improvements.

**Scope.** Technical writing in a business context (architecture docs, security findings, design proposals, technical reports, internal memos, RFCs). Excluded by stipulation: boredom from (1) lack of subject-matter interest in the reader, and (2) emotional opposition to the premise. Both are reader-side, not text-side.

---

## Part I — Research Report

### 1. The core theoretical anchor: the MAC Model of boredom

The most useful frame from psychology is Westgate & Wilson's **Meaning and Attentional Components (MAC) model** of boredom (Psychological Review, 2018), which integrates and supersedes earlier environmental, attentional, and functional theories. It defines boredom as an affective signal of **unsuccessful attentional engagement in valued goal-congruent activity**. Two independent components produce boredom:

- **Attentional component** — the reader cannot effectively engage. This happens when cognitive demand is mismatched to available resources, in either direction: *understimulation* (too easy, monotonous, predictable) OR *overstimulation* (too dense, too complex, too fast).
- **Meaning component** — the reader does not see the task as valuable or goal-congruent. The reader can't tell *why* this matters, or *where it's going*, or *what they'll get out of finishing*.

Boredom is produced when *either* component fails, independently. This is important for our skill: a paper can be boring because it's a fog of jargon (attention failure from overstimulation), because it grinds through obvious points in flat prose (attention failure from understimulation), or because the reader cannot tell what conclusion is being built toward (meaning failure) — and these need different fixes.

Eric's stipulated exclusions map cleanly onto this model. Subject-matter disinterest = a reader-side meaning failure independent of the text. Emotional opposition = a separate aversion, not boredom. What's left for our skill to assess is **text-driven** failure on either axis: properties of the prose that drive attention away or that fail to project meaning forward.

A complementary finding from the boredom-and-control literature (Struk, Scholer & Danckert 2021) is that boredom is also produced by **perceived lack of control over the situation** — including being unable to predict when something will end or what will come next. In reading, this maps to lack of signposting, lack of structure, and lack of forward-motion cues. The reader feels stuck.

### 2. The information-theoretic angle: surprise and uniform information density

A second body of work from psycholinguistics frames engaging text in information-theoretic terms. The **Uniform Information Density (UID) hypothesis** (Jaeger & Levy, and others) proposes that good prose distributes information evenly across the text — neither so flat that nothing happens (boredom from understimulation) nor so spiky that the reader gets cognitively overwhelmed (boredom from overstimulation). Words that are too predictable convey no information; words that are too surprising blow past the reader's processing capacity.

Recent work (Tsipidi et al. 2024) explicitly notes UID is not the whole story: writers also *deliberately* modulate information rate to "maintain interest" and "build compelling arguments." This connects directly to Eric's intuition about intermediate climaxes — well-shaped prose has an information-density contour that rises and falls.

There is converging neuroscience: prediction-error responses (the N400) modulate engagement and memory. Bill Birchard's *Writing for Impact* synthesizes this for popular consumption — the surest neural hook is **surprise**: surprising observations, unexpected analogies, well-placed metaphors. The dopamine response to surprise is a major engagement driver. Boring prose is prose where nothing surprises you.

### 3. The reader-expectation tradition: Gopen & Swan

The most operationalizable craft framework for technical prose is **Gopen and Swan's "The Science of Scientific Writing"** (American Scientist, 1990). Their core claim: readers do most of their interpretation based on *structural cues* — and prose feels muddled (and boring) when those cues are misplaced. Their main rules:

1. **Topic position** (start of sentence): old/familiar information that links backward and provides perspective. The reader needs to know "whose story is this sentence telling?" and "how does this connect to what I just read?" before they can absorb anything new.
2. **Stress position** (end of sentence, at syntactic closure): new, important information the writer wants emphasized. Readers naturally exert peak attention there.
3. **Subject and verb close together**: long gaps between them force the reader to hold context in working memory, which exhausts attention.
4. **Action in the verb**: not buried in nominalizations.
5. **One unit, one point**: every sentence/paragraph/section should serve a single function.

When these expectations are violated, prose feels like work. Repeated violation produces the specific texture of academic/bureaucratic boredom — the reader can parse it, but each sentence requires effortful re-construction. This is overstimulation-type boredom in MAC terms.

The same principles scale up: paragraphs have topic and stress sentences, sections have topic and stress paragraphs.

### 4. The technical-writing tradition: nominalization, passive voice, density

Technical writing handbooks (Williams' *Style*, Lanham's "Official Style," Pinker's *Sense of Style*, Duke/CU/OSU technical writing guides) consistently identify the same set of style failures that produce dull, sluggish prose:

- **Nominalization** — turning verbs into nouns ("performed an analysis of" instead of "analyzed"). Replaces real action verbs with weak "to be" constructions.
- **Excessive passive voice** — divorces actions from agents, adds words, removes momentum.
- **Long subject-verb gaps** — the reader has to hold "the system" in working memory for 18 words before learning what the system *did*.
- **Noun stacks** — "user authentication credential validation framework."
- **Hedging clutter** — "it could be argued that there is some evidence to suggest that perhaps..."
- **Throat-clearing openings** — "It is important to note that..." / "In recent years there has been growing interest in..."
- **Wordiness** — "due to the fact that" instead of "because."

Lanham's "Official Style" is the diagnostic name for prose that exhibits *all* of these together — the characteristic register of bureaucracies, consultancies, and legal departments. It is not unclear (a careful reader can decode it) but it is exhausting and dull. This corresponds to the overstimulation pole of MAC attentional boredom.

### 5. The sentence-rhythm tradition: Gary Provost

The most famous statement of this is Gary Provost's *100 Ways to Improve Your Writing* (1985), in his "This sentence has five words" passage. The point: **sentence-length monotony is sonically boring, even if individual sentences are well-formed.** Variation in sentence length creates rhythm; rhythm sustains attention. The same point applies to syntactic variety (always subject-verb-object), to opener variety (always starting with "The X..."), and to paragraph length.

This is squarely in MAC's understimulation territory: the reader's attention drifts because the prose offers no fluctuation to re-engage with.

### 6. The narrative-arc tradition

Eric's intuition about intermediate climaxes connects to Freytag-style story arc theory and its modern computational analogues. Boyd, Blackburn & Pennebaker's "The narrative arc" (Science Advances 2020) showed that even nonfiction texts (NYT articles, TED talks, Supreme Court arguments) follow measurable structural dimensions:

1. **Staging** — establishing context and setting (front-loaded; uses prepositions, articles)
2. **Plot progression** — forward motion through the material (uses pronouns, auxiliary verbs, connectives)
3. **Cognitive tension** — buildup of conflict/problem/stakes that resolves at a climax (peaks late in the text)

Engaging nonfiction has these. Boring nonfiction often has staging but flatlines on plot progression and never builds cognitive tension. It just *describes*. This maps to MAC's meaning component: there is no felt direction toward a payoff, so the reader stops caring about completing it.

For technical business writing specifically, "cognitive tension" usually means the **problem-solution arc**: a real problem with stakes, an exploration of why it's hard, the resolution. A document that opens with "This document describes the architecture of X" has neither a problem nor stakes nor anywhere to go — it is structurally pre-committed to boredom.

For longer documents, fiction-craft writers also discuss **tension peaks and releases** within sections — periods of buildup followed by a smaller payoff (a finding, a "so what," a resolved sub-question), then new buildup. Constant high tension is exhausting; constant low tension is dull; the rhythm of the alternation is what sustains engagement.

### 7. The "answer first" tradition: BLUF and the Pyramid Principle

For business writing specifically, the dominant operationalization of "meaning forward" is Barbara Minto's **Pyramid Principle** and the related **BLUF** ("Bottom Line Up Front") convention from military and management communication. The core claim: in a business context, readers come with a question and want the answer first, supported by reasons, supported by evidence. Prose that builds inductively to a conclusion at the end ("we did X, then Y, then Z, therefore A") buries the lede and forces the reader to invest effort before knowing whether it's worth it.

In MAC terms, BLUF preserves meaning throughout: the reader knows from sentence one *what* is being argued and *why it matters*, so every subsequent paragraph has a slot to attach to.

The journalistic equivalent is "don't bury the lede." The same anti-pattern shows up in technical writing as putting "Why" before "What" — programmers especially tend to walk through the reasoning chain first, "saving" the conclusion for the end as if rigor required suspense. Suspense doesn't help technical writing; it just delays the reader's ability to triage and contextualize.

### 8. Bringing it together

The seven traditions converge on a coherent picture. Boring prose fails the reader on at least one of three axes:

- **Direction** — the reader can't tell where the text is going, what is being argued, or why it matters. (MAC meaning failure; Pyramid Principle / BLUF / lede burying / cognitive tension flatness)
- **Density** — the information-per-sentence rate is wrong. Either too low (every sentence makes one obvious point already implied by the previous; nominalized fog with no real claim landing) or too high (sentences pack three new concepts into one nominalized clause with subjects and verbs strung apart). (MAC attention failure from understim/overstim; UID violations; Williams/Lanham diagnoses)
- **Texture** — the prose is sonically and structurally monotonous. Same sentence length, same sentence shape, same opener, same syntactic move, no rhythm. (MAC attention failure from understimulation; Provost; sentence-variety craft tradition)

Underlying all three is a fourth: **surprise**. Prose that reliably says only what the reader could already predict has no informational pulse. Surprising claims, vivid examples, unexpected analogies, and well-placed concrete details create the small dopaminergic re-hooks that sustain attention through longer passages.

---

## Part II — Taxonomy of Boringness Dimensions

A taxonomy designed to be (a) operationalizable as evaluation rubric items and (b) actionable as concrete suggestions. Three top-level dimensions, each with sub-dimensions. This intentionally maps onto the three-axis synthesis above (Direction / Density / Texture) plus a cross-cutting Surprise dimension.

### D1. Direction — does the reader know where this is going and why?

Failures here are **meaning-component** failures in MAC terms. They are the most consequential category: density and texture problems make a document tiring to read, but a Direction failure makes the reader put it down.

| Code | Sub-dimension | Failure pattern | Concrete signals |
|---|---|---|---|
| D1.1 | **Buried thesis** | Main claim/recommendation appears late or never | Document opens with background, history, or methodology; first ~10% contains no claim; section headers describe topics not findings |
| D1.2 | **Missing stakes** | Reader can't tell why the topic matters | No problem stated; no consequences of getting it wrong; no audience signal ("for whom is this") |
| D1.3 | **No forward motion** | Each section/paragraph describes rather than advances | Sections are nominal ("Architecture", "Background") rather than claim-shaped ("Why we chose X over Y"); paragraphs end without a "so what" |
| D1.4 | **No signposting** | Reader can't predict structure or location | No roadmap in intro; transitions absent or generic ("Additionally", "Furthermore"); section openings don't connect to what came before |
| D1.5 | **Flat tension** | No problem-solution arc, no buildup-and-resolution rhythm | Document presents conclusions without the difficulties they overcame; no acknowledgment of alternatives considered and rejected; nothing is at stake within sections |
| D1.6 | **Topic-position drift** | Sentences don't link back to the prior topic | Sentence subjects keep shifting; the "story" of a paragraph is hard to track; pronouns lack clear referents |

### D2. Density — is the information rate well-calibrated?

Failures here are **attentional-component** failures, of either the overstimulation or understimulation variety.

| Code | Sub-dimension | Failure pattern | Concrete signals |
|---|---|---|---|
| D2.1 | **Padding / wordiness** (understim) | Sentences use many words to convey little | Phrases like "due to the fact that," "in order to," "it is important to note that"; sentences that could be cut by 30%+ without loss |
| D2.2 | **Nominalization fog** (overstim+understim) | Real actions hidden in noun phrases | High ratio of -tion, -ment, -ance, -ity nouns; main verbs are mostly forms of "to be" or "have"; "performed an analysis of" patterns |
| D2.3 | **Passive overhang** | Habitual passive voice without reason | Passive constructions where the agent matters and is omitted; "it was determined that" patterns |
| D2.4 | **Subject-verb separation** (overstim) | Long noun phrases interrupt subject-verb-object | Sentences where the verb appears 10+ words after the subject; nested modifiers between them |
| D2.5 | **Obvious claims** (understim) | Sentences assert what the reader already knows or just inferred | Restating the previous sentence; defining terms the audience clearly knows; no informational delta |
| D2.6 | **Idea overload spikes** (overstim) | Single sentences cramming 3+ new concepts | Sentences with multiple novel terms introduced at once; sentences requiring re-reading |
| D2.7 | **Hedging clutter** | Excessive qualification dilutes claims | Stacked hedges ("it could perhaps be argued that there is some evidence to suggest..."); strong claims softened to invisibility |
| D2.8 | **Throat-clearing** | Sentences that exist only to introduce other sentences | "It is worth noting that..."; "As mentioned previously..."; "The next section will discuss..." (when the heading already says so) |

### D3. Texture — is the prose rhythmically alive?

Failures here are **attentional understimulation** in MAC terms — even well-formed sentences become hypnotic when uniform.

| Code | Sub-dimension | Failure pattern | Concrete signals |
|---|---|---|---|
| D3.1 | **Sentence-length monotony** | All sentences cluster around one length | Low standard deviation of sentence length; long stretches of similar-length sentences; absence of any short punchy sentences |
| D3.2 | **Syntactic monotony** | Same syntactic shape repeats | Every sentence opens "The X is..." or "When Y, then Z..."; no variation between simple/compound/complex |
| D3.3 | **Opener monotony** | Sentences start the same way | Many consecutive sentences beginning with the same word, the same part of speech, or the same construction (e.g., "The system...") |
| D3.4 | **Paragraph monotony** | All paragraphs the same length and shape | Wall-of-text paragraphs of identical visual weight; no short emphatic paragraph for variety |
| D3.5 | **Vocabulary flatness** | Limited verb and noun palette | Repetitive use of the same generic verbs ("uses", "provides", "enables"); low type-token ratio in content words |

### D4. Surprise (cross-cutting) — does the reader ever encounter the unexpected?

This is not strictly a separate failure mode but an absence that amplifies everything else. Even technically well-structured prose feels boring without it.

| Code | Sub-dimension | Failure pattern | Concrete signals |
|---|---|---|---|
| D4.1 | **No concrete examples** | Abstractions never grounded | Long passages without a single specific instance, number, name, or scenario |
| D4.2 | **No vivid imagery or analogy** | Reader given no mental picture | Pure abstraction; no metaphors that connect new material to familiar; no useful comparisons |
| D4.3 | **No counterintuitive claims** | Nothing the reader didn't already assume | Document confirms expectations sentence by sentence; no "surprisingly," no "we expected X but found Y," no friction with default beliefs |
| D4.4 | **No specificity** | Generic where it could be precise | "Significant improvements" instead of "47% reduction"; "various stakeholders" instead of "the security team and finance"; "modern approaches" instead of named approaches |

---

## Part III — Rubric Sketch

A possible structure for how the skill could evaluate a document and produce guided suggestions. This is intended as a starting design, not a final spec.

### Phase 1 — Document profiling

Before scoring, gather basic structural facts: word count, sentence count, paragraph count, section structure, presence of headings, position of first explicit claim, position of explicit "why this matters" statement. Many Direction-axis judgments depend on this profile.

For technical business writing specifically, also detect document genre (proposal / report / RFC / status update / architecture doc / finding writeup), because the appropriate balance shifts. A status update should be ~95% BLUF; an architecture decision record needs context-then-decision; a security finding needs problem-impact-recommendation in that order.

### Phase 2 — Per-dimension scoring

For each sub-dimension in the taxonomy, the skill produces:

1. **A score** on a 0–4 scale (0 = no problem detected, 4 = severe). For computable dimensions (sentence length variation, nominalization rate, hedging density, passive ratio) the score can be partly mechanical; for judgment-heavy dimensions (buried thesis, missing stakes, no surprise) it relies on LLM judgment over the document.
2. **Evidence** — specific spans from the document that exemplify the problem. Without this, suggestions feel generic and easy to dismiss.
3. **An aggregated D-axis subscore** for Direction, Density, Texture, and Surprise.

A document's overall "boringness profile" is the four subscores, not a single number — because the *kind* of boring matters for the fix. A document scoring high on Direction failures needs restructuring; a document scoring high on Texture needs sentence-level rewriting; these are very different interventions.

### Phase 3 — Prioritized suggestions

The skill should not dump every finding. A useful intervention is ranked and constrained. A possible priority ordering for technical business writing:

1. **Direction failures first** — fix these and the document becomes worth reading even if other problems remain.
2. **Top one or two Density failures** — pick the highest-impact dim (often nominalization or padding for technical writers).
3. **One Texture observation** — usually sentence-length monotony or opener monotony.
4. **One Surprise prompt** — usually "where is the most interesting/counterintuitive finding, and is it given enough prominence?"

For each, output: (a) the specific span(s), (b) what is wrong in plain language, (c) one rewritten example or a concrete prompt for the writer to address.

### Phase 4 — Guided revision mode

Beyond a one-shot evaluation, the skill could offer an iterative mode where the writer accepts/rejects suggestions and the skill re-scores. This is where the "guided" aspect lives: rather than a static report, a back-and-forth that focuses on one dimension at a time. The order matters — fix Direction before Density before Texture, because rewrites at the small scale are wasted if the document gets restructured later.

### Phase 5 — Things the skill should NOT do

- **Don't mistake dense for boring.** Technical content is sometimes legitimately dense for its audience. The skill needs to consider whether density is *unmotivated* (pure nominalization fog adding no information) versus *motivated* (genuinely high information rate for an expert reader).
- **Don't penalize useful absence of narrative.** A reference doc, an API spec, or a runbook should *not* have cognitive tension or surprise. Genre detection (Phase 1) gates which dimensions apply.
- **Don't reward surface signals at the expense of meaning.** Sentence-length variation can be gamed by a writer who scatters short sentences randomly; the variation must serve emphasis. The skill's surprise/Direction judgments need to anchor the texture judgments, not the other way around.
- **Don't lecture.** The output should be diagnostic and specific, not a writing-craft mini-essay attached to every suggestion.

### Open design questions worth resolving before building

1. **How is "the audience" specified?** Many calls (jargon level, expected stakes framing, even what counts as surprising) depend on it. Is the audience an input parameter, inferred from the document, or both?
2. **Whole-document versus chunk-level evaluation?** Direction is a whole-document property; Density and Texture can be assessed per-paragraph. The pipeline likely needs both passes.
3. **How much is mechanical vs LLM-judged?** A defensible split: Texture and parts of Density are highly mechanical (and cheap); Direction and Surprise are inherently LLM-judged. This affects cost and reproducibility.
4. **What's the calibration target?** "Boringness" needs an anchor — examples of boring-but-fixable, boring-and-unfixable, and not-boring documents in the target genre. Without calibration examples, scoring will drift.
5. **Suggestion granularity.** Does the skill propose specific rewrites (risky, opinionated, sometimes wrong about technical content) or only point at problems and suggest moves (safer, less actionable)? A hybrid (rewrite small spans, point at large ones) is probably right.

---

## Key sources for further reading

- Westgate, E. C., & Wilson, T. D. (2018). *Boring Thoughts and Bored Minds: The MAC Model of Boredom and Cognitive Engagement.* Psychological Review. — The theoretical anchor.
- Gopen, G. D., & Swan, J. A. (1990). *The Science of Scientific Writing.* American Scientist 78(6). — The most operationalizable craft framework.
- Williams, J. M. *Style: Lessons in Clarity and Grace.* — The standard reference on sentence-level technical-writing failures.
- Minto, B. *The Pyramid Principle.* — The canonical statement of BLUF / answer-first structure for business writing.
- Provost, G. (1985). *100 Ways to Improve Your Writing.* — The "this sentence has five words" rhythm argument.
- Boyd, R. L., Blackburn, K. G., & Pennebaker, J. W. (2020). *The narrative arc: Revealing core narrative structures through text analysis.* Science Advances. — Computational treatment of narrative structure in nonfiction.
- Tsipidi, E. et al. (2024). *Surprise! Uniform Information Density Isn't the Whole Story.* — Information-density contours in long-form discourse.
- Birchard, B. *Writing for Impact.* — Popular synthesis of the surprise/dopamine engagement literature.
- Lanham, R. *Revising Prose.* — The "Official Style" diagnosis.
- Pinker, S. *The Sense of Style.* — Modern synthesis of much of the above for general writers.
