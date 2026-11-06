source(testthat::test_path("..", "..", "..", "scripts", "parkinson_models.R"), local=TRUE)

research_metadata <- function() {
  data.frame(
    gsm = paste0("S", 1:8), donor = paste0("D", 1:8),
    group = rep(c("Control", "PD"), each=4),
    `age at death` = c(60,70,80,90,65,75,85,78),
    `rna integrity number (rin)` = c(4,5,6,8,4.5,5.5,6.5,7.5),
    `post mortem index (pmi)` = c(10,20,30,15,12,23,18,25),
    `gender (m: male, f: female)` = rep(c("M","F"),4),
    check.names=FALSE
  )
}

testthat::test_that("research metadata never silently imputes or duplicates donors", {
  x <- research_metadata()
  prepared <- prepare_research_metadata(x)
  testthat::expect_identical(levels(prepared$condition), c("Control","PD"))
  testthat::expect_equal(mean(prepared$age_z), 0, tolerance=1e-10)
  x$donor[2] <- x$donor[1]
  testthat::expect_error(prepare_research_metadata(x), "DUPLICATE_DONOR")
  x <- research_metadata()
  x[["rna integrity number (rin)"]][1] <- NA
  testthat::expect_error(prepare_research_metadata(x), "MISSING_COVARIATE")
})

testthat::test_that("rank deficient designs are rejected before fitting", {
  x <- prepare_research_metadata(research_metadata())
  x$age_z <- as.numeric(x$condition=="PD")
  testthat::expect_error(check_research_design(x, ~age_z+condition), "RANK_DEFICIENT")
})

testthat::test_that("quality selections depend only on recorded RIN", {
  x <- prepare_research_metadata(research_metadata())
  testthat::expect_equal(which(research_subset(x,"rin5")), c(2,3,4,6,7,8))
  testthat::expect_equal(which(research_subset(x,"rin6")), c(3,4,7,8))
  testthat::expect_true(all(research_subset(x,"full")))
})
