library(psych)
library(dplyr)

# # Turn the correct column to a binary variable and make other random effects factors
# timing_data$correct = ifelse(timing_data$correct == "Y", 1, 0)
# timing_data$PID = as.factor(timing_data$PID)
# timing_data$bug = as.factor(timing_data$bug)
# timing_data$condition = as.factor(timing_data$condition)
# 
# # continuous numeric variable
# timing_data$time_minutes = as.numeric(timing_data$time_minutes)
# 
# # make numPrev column
# timing_data$num_prev = timing_data$task_no - 1
# timing_data$num_prev = as.factor(timing_data$num_prev)
# 
# # columns for whether or not they looked at the buggy method and whether or not they had a patch
# timing_data$looked_at_buggy_method = ifelse(is.na(timing_data$ttff_buggy_method), FALSE, TRUE)
# timing_data$had_patch = timing_data$condition %in% c("overfitting", "correct")
# 
# # This is how many tasks we have recorded
# paste0("All in all, we recorded data for ", nrow(timing_data), " tasks.")
# 
# # P2 t3 was cut off 5 minutes early
# # make column for that, add to model, remove if not explanatory of much variance
# timing_data$cut_off = FALSE
# timing_data$cut_off[timing_data$PID == 'P2' & timing_data$task_no == 3] = TRUE
# 
# ############
# 
# # Add columns for in-study survey per participant-task
# survey = read.csv("patchwork_survey.csv")
# 
# # Find duplicate PIDs and rename to P1-0 through P6-0
# which(tolower(survey$Q24) == "p1")
# survey$Q24[4] = "P1_0"
# survey$Q24[5] = "P2_0"
# survey$Q24[6] = "P3_0"
# survey$Q24[7] = "P4_0"
# survey$Q24[8] = "P5_0"
# survey$Q24[9] = "P6_0"
# 
# # Q24 -- PID
# # Q1_10 -- mental/perceptual activity
# # Q2_1 -- time pressure
# # Q3_1 -- performance
# # Q4_1 -- effort
# # Q5_1 -- frustration
# 
# # and so on for t2:
# # Q44_10 -- mental/perceptual activity
# # Q45_1 -- time pressure
# # ...
# 
# # and for t3:
# # Q50_10 -- mental/perceptual activity
# # Q51_1 -- time pressure
# # ...
# 
# # Goal: in the long run, change the column names of these in a cleaning script to make things easier
# # For now, just create average cognitive load for t1, 2, and 3
# 
# data.frame(index = seq_along(survey), name = names(survey))
# survey$Q24 = as.factor(survey$Q24)
# survey[, 20:24] = lapply(survey[, 20:24], as.numeric)
# survey[, 26:30] = lapply(survey[, 26:30], as.numeric)
# survey[, 32:36] = lapply(survey[, 32:36], as.numeric)
# 
# # FIXME: some people did not drag the scale and meant 0 -- change NaNs to 0? might be more accurate to what really happened than missing data
# 
# # level of performance (Q3_1, Q46_1, Q52_1) should be inverse
# survey$Q3_1 = 21 - survey$Q3_1
# survey$Q46_1 = 21 - survey$Q46_1
# survey$Q52_1 = 21 - survey$Q52_1
# 
# # Note: na.rm = TRUE allows there to be NA values dropped from the average
# survey$t1_cognitive_load = rowMeans(survey[, 20:24], na.rm = TRUE)
# survey$t2_cognitive_load = rowMeans(survey[, 26:30], na.rm = TRUE)
# survey$t3_cognitive_load = rowMeans(survey[, 32:36], na.rm = TRUE)
# 
# # Now set ONE column in timing_data which has these averages, matching with PID and task number
# lookup = as.matrix(survey[, c("t1_cognitive_load", "t2_cognitive_load", "t3_cognitive_load")])
# rownames(lookup) = survey$Q24
# 
# timing_data$cognitive_load = lookup[
#   cbind(
#     match(timing_data$PID, rownames(lookup)),
#     timing_data$task_no
#   )
# ]
# 
# # TODO: OCEAN personality scores, if we want
# 
# # Read in demographic data
# screener = read.csv("patchwork_screener.csv")
# 
# # Chop off headers in surveys
# screener = screener[3:nrow(screener), ]
# survey = survey[4:nrow(survey), ]
# 
# # Find demographics: min max median age and YOE
# screener$Age = as.numeric(screener$Age)
# paste0("Median age: ", median(screener$Age, na.rm=TRUE))
# paste0("Minimum age: ", min(screener$Age, na.rm=TRUE))
# paste0("Maximum age: ", max(screener$Age, na.rm=TRUE))
# 
# # Q11 is YOE
# screener$Q11 = as.numeric(screener$Q11)
# paste0("Median YOE: ", median(screener$Q11, na.rm=TRUE))
# paste0("Minimum YOE: ", min(screener$Q11, na.rm=TRUE))
# paste0("Maximum YOE: ", max(screener$Q11, na.rm=TRUE))
# 
# # Q13 is gender, Q16 is are you a student (answers: Yes, I am a Master's student, Yes, I am a Ph.D. student, No, Yes, I am undergraduate), Q10 is have you worked or are you currently working... with "Yes, I currently work at one" being the professional label
# as.data.frame(table(screener$Q13))
# 
# ####
# 
# # Prepare columns and check for collinearity
# 
# # Q20 is IntelliJ IDEA IDE experience and Q21 is Java
# # Subset screener to IntelliJ/Java experience
# exp_vars = screener[, c("Q20", "Q21")]
# 
# exp_vars$Q20 = ifelse(screener$Q20 == "Not familiar at all",  1,
#                       ifelse(screener$Q20 == "Slightly familiar",     2,
#                              ifelse(screener$Q20 == "Moderately familiar",   3,
#                                     ifelse(screener$Q20 == "Very familiar",         4,
#                                            ifelse(screener$Q20 == "Extremely familiar",    5, NA)))))
# 
# exp_vars$Q21 = ifelse(screener$Q21 == "Not knowledgeable at all",  1,
#                       ifelse(screener$Q21 == "Slightly knowledgeable",     2,
#                              ifelse(screener$Q21 == "Moderately knowledgeable",   3,
#                                     ifelse(screener$Q21 == "Very knowledgeable",         4,
#                                            ifelse(screener$Q21 == "Extremely knowledgeable",    5, NA)))))
# 
# # estimates the correlation between two ordinal variables
# polychoric(exp_vars)
# 
# # Average into single component, since they covary highly enough
# screener$java_intellij_experience = rowMeans(exp_vars, na.rm = TRUE)
# 
# screener = rename(screener, professional_YOE = Q11)
# survey = rename(survey, PID = Q24)
# 
# # if number is low, we can count years of experience and java_intellij_experience as different predictors, not impacting model collinearity
# cor(screener$professional_YOE, screener$java_intellij_experience, 
#     use = "complete.obs", method = "spearman")
# 
# screener$PID = as.factor(screener$PID)
# 
# # Look at correspondence between professional identity and YOE
# # Singleton category is problematic, so we'll say unemployed participant is actively in their professional career
# screener$professional_identity = ifelse(
#   screener$professional_identity == "Unemployed",
#   "Professional",
#   screener$professional_identity
# )
# # Also combine to "grad student"
# screener$professional_identity = ifelse(
#   screener$professional_identity == "PhD" | screener$professional_identity == "Masters",
#   "Grad",
#   screener$professional_identity
# )
# 
# screener$professional_identity = as.factor(screener$professional_identity)
# 
# # Boxplot: Years of Experience by Professional Identity
# boxplot(professional_YOE ~ professional_identity, data = screener,
#         main = "YOE by Professional Identity",
#         xlab = "Professional Identity",
#         ylab = "Years of Experience")
# 
# # Means of YOE within each category
# # PhD and Masters have similar average YOE, but have different professional identities, so it may be valuable to include this as a predictor
# aggregate(professional_YOE ~ professional_identity, 
#           data = screener, 
#           FUN = mean)
# 
# # Add column to timing_data for professional YOE, java_intellij_experience, professional identity
# timing_data = merge(timing_data, 
#                     screener[, c("PID", "java_intellij_experience", "professional_YOE", "professional_identity")],
#                     by = "PID",
#                     all.x = TRUE)
# 
# # Subset to self-efficacy. columns Q2_1.1, Q2_2--8
# cols = c("Q2_1.1", "Q2_2", "Q2_3", "Q2_4", "Q2_5", "Q2_6", "Q2_7", "Q2_8")
# se = survey[, cols]
# # See all unique values across all your SE columns
# lapply(se[cols], unique)
# # Numericize and average
# efficacy_map = c("Strongly Disagree" = 1,
#                  "Somewhat disagree" = 2,
#                  "Neither agree nor disagree" = 3,
#                  "Somewhat agree" = 4,
#                  "Strongly agree" = 5)
# se[cols] = lapply(se[cols], function(x) efficacy_map[x])
# survey$self_efficacy = rowMeans(se[cols], na.rm = TRUE)
# # Add column to timing_data for self_efficacy
# timing_data = merge(timing_data,
#                     survey[, c("PID", "self_efficacy")],
#                     by = "PID",
#                     all.x = TRUE)
# 
# #####
# 
# # Potential values for correctness: Y, N, P, IDK
# just_idk = subset(timing_data, think_correct == "IDK")
# patch_just_idk = subset(timing_data, think_patch_correct == "IDK")
# correct_num_idk = nrow(just_idk)
# patch_correct_num_idk = nrow(patch_just_idk)
# paste0("Participants didn't know if their fix was correct for ", correct_num_idk, " tasks.")
# paste0("Participants didn't know if the patch was correct for ", patch_correct_num_idk, " tasks.")
# 
# # Make df with dropped rows if think_correct or think_patch_correct is IDK
# correct_no_idk = subset(timing_data, think_correct != "IDK")
# patch_correct_no_idk = subset(timing_data, think_patch_correct != "IDK")
# 
# # Need to remove IDK and treat P/Y as true and N as false
# correct_no_idk$think_correct = ifelse(correct_no_idk$think_correct == "Y" | correct_no_idk$think_correct == "P", 1, 0)
# patch_correct_no_idk$think_patch_correct = ifelse(patch_correct_no_idk$think_patch_correct == "Y" | patch_correct_no_idk$think_patch_correct == "P", 1, 0)
# 
# # Remove all "control" conditions and prepare patch_correct column for visualization
# had_patch = subset(patch_correct_no_idk, condition != "control")
# had_patch$patch_correct = ifelse(had_patch$condition == "correct", 1, 0)
# 
# # Potential values for submitting: Y, N, NQ, P
# 
# # TODO: submission question

