Outstanding questions/issues:

* I’m seeing a lot of errors: Some models (especially those on the subsetted dataframes) are still failing, especially those in the gaze models for the hypothesis testing, due to random effects not being estimable   

- Claire response: 

To scope, I am addressing the error you describe above, random effects
not being estimable, which usually shows up as a "boundary (singular) fit". I
saw other errors in the output, like "Hessian is numerically singular," a
convergence failure, etc., and these are all different. So you have to read the
warning or reason the model is failing and research what it means to identify
potential fixes.  

To the issue you mention above: A random intercept needs replication within
levels to estimate variance.  If you're including something like (1|PID), you're
asking it to account for "how much much participants differ from one another on
average" in the model.  That needs multiple observations per participant (or bug
for example in (1|bug)).  Subsetting removes replication, especially for the
gaze data because only 2/3 of the trials have a patch at all, and we also lose a
bunch of gaze-invalid rows.  So you're (almost certainly) ending up with
subsetted data where many participants have only 1 observation, which means
(1|PID) has nothing to estimate its variance from.

Also, this doesn't always make a model crash, it'll run and just warn "boundary
(singular) fit," which means the random-effect variance collapsed to ~0. You can
check with table(table(df$PID)).

Options to solve this:
1. fixed effects instead of random, which is what you have in your code trying
to do with glm on line 521.  That's going to eat your dof.  More importantly, it
strikes me as a weird and difficult-to-justify-wrt-reality modeling choice, that
e.g., a bug is a fixed effect.
2. Drop random effects without replications.  My guess is that the bugs survive
subsetting better than participants, but this is an empirical question so you
just have to check (as above). 

This is pretty normal in statistics. You can only report structure your
data supports.

3. Don't subset and use interaction on the full data instead, with a trick.
    
Didactic explanation time since I don't know how much you know.

Consider a simple model with no drama and tons of data (I'm ignoring random
effects for now): 
    correct ~ had_patch + ttff_patch

This says "build a model where you predict correctness based on whether the
participant had the patch and also time to first fixate on it":

   correct ~ β0 + β1·had_patch + β2·ttff_patch

This model assumes had_patch and ttff_patch are additive and independent in
their effects. Each gets its own slope that applies everywhere regardless of
what's going on with the other.  
  
It _also_ makes no sense, conceptually, in a modeling sense, because ttff_patch
only makes sense where you actually _have_ a patch. That's why you're subsetting
in your code (though as you know, you don't technically have to, since R will
drop the rows where ttff_patch is NA). Regardless, you run out of enough tasks
per participant to estimate random effects. Which is a bummer, sad trombone. 

OK, then, if it drops anything with NA for one of the model variables
(ttff_patch in this case), is there a way to keep them? Short answer, yes: you
can just set ttff_patch to some number where there is no patch. I'm gonna
advocate that "some number" be 0, because it's a sensible choice that's a bit
more error-resistent. If we set ttff_patch to 0 where had_patch is 0, the model
can now see all 127 tasks and better estimate random effects where previously it can't
because of subsetting. 

It also immediately introduces an obvious new problem, because the zeros are
fake and the model will learn from fake data.  That's definitely worse
than dropping the rows/random effects in the first place.  

Fortunately, we can fix it. 

Enter: interactions. Interactions say the slope of one predictor depends on the
value of the other. Or "the effect of looking at the patch sooner is allowed to
be different depending on whether you had a patch." Mathematically it's the product
of two columns, which is why you need to put a number (0, but literally anything
would be fine) in for ttff_patch in place of the NAs, for it to be computable.

The full/canonical form would look like:
    correct ~ had_patch * ttff_patch

Using * in R means "both main effects plus their interactions", so this expands to: 
    correct ~ β0 + β1·had_patch + β2·ttff_patch + β3·(had_patch × ttff_patch)

This is _one hundo percent not what we want._ I will explain why after I explain
what we do want, which is: 
    correct ~ had_patch + had_patch:ttff_patch

[I am NOT including the random effects there because I don't need to explain
them, but I assume you'd include them in the ACTUAL model]

THAT expands to:
    correct ~ β0 + β1·had_patch + β2·(had_patch × ttff_patch)

The important difference is that it DOESN'T include a main effect for
ttff_patch. That's why the : is important instead of the *. 

Immediate benefit: this matches reality, since "looking at patch sooner" can
only have an effect when there was a patch at all, so keeping "ttff_patch" on
its own is a nonsensical modeling choice. 

Here, assuming (VERY IMPORTANT) we gave ttff_patch a number (0) where had_patch
is 0, the interpretation is as follows:  

- β0 (intercept): the baseline outcome when both predictors are 0. The two
  predictors are had_patch and the product had_patch:ttff_patch.  Whenever
  had_patch = 0, the product term is 0 automatically no matter what ttff_patch
  is, so the intercept is really "had_patch = 0" (control!).  The value of
  ttff_patch never affects the computation of the intercept because had_patch
  zeros it out regardless. 
- β1 (had_patch): the shift in outcome from having a patch, _evaluated at
  ttff_patch = 0._ The whole thing this model is asking is, "how does the effect
  of having a patch depend on ttff_patch".  If looking at a patch immediately
  helps a lot and looking at it later helps less, then there's no single "patch
  effect", which is basically the whole premise of the model. So
  β1 is the patch-vs-control gap at the ttff_patch value where the other term
  (interaction) is 0 but had_patch _isn't_, which is ttff_patch = 0 (looked at
  the patch instantaneously).  
  
  (There are other choices here (we could center it on the average ttff_patch
  for example), but I actually don't think we care/need to, because the point of
  THIS model is to figure out if ttff_patch matters, not whether existence of
  patch does).
- β2 (the had_patch × ttff_patch interaction): This is the slope of ttff_patch
  for people who actually had the patch, or "as time-to-first-patch-fixation goes
  up, how does the outcome change, for patch-havers?" For control rows, had_patch
  = 0, so the whole term is 0 × ttff_patch = 0, and they contribute nothing to β2.
  So β2 is estimated purely from patch trials (had_patch = 1), which is exactly
  what we want. But! The control trials are still around and can contribute data to
  the random effects (which isn't in the R above but you can obviously add them
  back).  Without screwing up anything else.

Tradeoffs between options 3 and 2: 3 is slightly more complicated to justify
(that the RQ can be answered by looking at the coefficient of the interaction
term), I guess (though, like, this doesn't bother me, because it's TRUE). It's
also a little more error-prone to implement, so, _PLEASE_ stop introducing
copy-paste bugs in your R code.  Ask Claude Code to scrutinize it carefully for
such errors, if nothing else. 

* NEW FROM CLAIRE, related to the fault localization test you want to run, and a
DIFFERENT ERROR.  On line 617, you do a logistic regression of looked_at_buggy_method ~
condition... and that gives you a `Warning:  Hessian is numerically singular:
parameters are not uniquely determined`.

This is a separation problem, namely that a fixed effect (condition) perfectly
predicts the binary outcome.  Data breaks down as:

           did NOT look   looked
  control        8          28
  correct        0          34
  overfitting    2          32

All people with the correct condition looked at the buggy method, so correct
perfectly predicts looked = true, which ONE HUNDO PERCENT freaks out logistic
regression because it wants to set the coefficient to +infinity.  

Fortunately, this is...good? Actually? "everyone with a correct patch looked at
the buggy method" supports your hypothesis, the model is choking because the
effect is so strong. 

There are some options here but I think a small-sample exact test (like Fisher's
exact on the table) instead of a regression is probably the most
straightforward and generally less stupid than trying to model around a
regression coefficient of +infinity. 

The other thing you probably should do, though, is also collapse overfitting into
correct to just compare "has patch" with "control".  Your logistic regression
won't choke there but is probably still overkill, Fisher's exact on a 2x2 table
is fine. 

THAT SAID I think "time to first look at buggy method" is almost certainly more
interesting (I hope?), but that needs a survival model. You want to look at
residuals for this (you have a comment) before deciding and sure, you can do
that, but it's pretty conceptually clear that it's a survival model situation.
The event is first fixation on the buggy method (ttff_buggy_method) and
people who never looked are censored (not dropped, which is what's currently
happening). 

This would be extra nice because you can look at "whether you ever looked" and
"how quickly" in a single model instead of splitting them into a logistic and
(broken) linear model (as the code now does it).  

* Survival analysis for regressions with time as the outcome (time to first fixation on buggy method, time\_minutes)? Still have not solved the skewed residuals problem  

- Claire response: first, yes, survival analysis is the right thing to do. I'm a
little confused by "have not solved skewed residuals" because by my
understanding, that's what survival analysis does/solves for us (fixes the skew on the
residual caused by the right-censoring of the data). 

Cox does have a proportional-hazards assumption (instead of a residual-normality
assumption) (namely: each predictor's effect on the hazard is constant over
time), so you need to check it, apparently cox.zph() will do this for you
(Schoenfeld residuals), you want a non-significant result. 

BUT. I want to double check that the status (computed line 92) you're using the models you've
started is the status you want to use.  I think it's only looking at time to completion,
not success/correctness.  The y-axis on the KM curve per line 410 is "probability
of failing to create a fix", which isn't what your event is in the survival
function.  The event is "time to stop". This probably warrants a github issue,
honestly, so I'll file one after I put Charlie to bed. 

* Should we include condition as a predictor for analyses on gaze data where participants had a patch? Has two levels: overfitting, correct. We saw similar effects from both types of patches on response time  

- Claire response: depends on what you're predicting/outcome, and you should
test this per model, in the same way I did for the previous paper (and as I
think we've discussed previously). You absolutely don't want to drop it for
correctness because my tired eyeballing says that condition is the single
strongest predictor there.  So for any model where correct is the outcome
variable, you need to keep it. 

For timing/effort/process gaze outcomes, they do look alike, just smell
checking.  This is consistent IIRC with a lot of what we saw in 24, for time,
but I could be misremembering.  So for those outcomes condition is probably a weak
covariate and is mostly costing you a degree of freedom, aka a bummer with small
data, so in those models you probably do want to drop it. 

But be principled about it, i.e., test whether it matters (LRT,
anova(model_with, model_without) or wald term) and model accordingly. This is
what we did in 24 and isn't p-hacking because you're being up
front about how you're testing/deciding what to keep.

Conceptual thing: "we saw similar effects on response time" is a statement 
about condition's effect being small.  But you're basically asking "should I
keep condition in models that are testing _other outcomes_." So should it be
kept as a covariate.  What matters there is whether it's a CONFOUNDER of the
relationship you care about (e.g., does which patch type they  got impact the
ttff_patch -> outcome connection?).  You want to test that, and the effect of
condition on its own isn't the question that actually matters, but 
rather the impact of condition on the thing you _do_ care about. 

* Still haven’t selected outliers definitively but P1t1 needs to go (by inspection it is very spotty because they were far away from the trackbox)