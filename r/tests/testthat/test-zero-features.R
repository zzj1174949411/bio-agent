test_that("all-zero features follow the validated input contract and are logged", {
  fixture <- make_bulk_fixture(seed = 42L)
  counts <- rbind(fixture$counts, ALL_ZERO = rep(0L, ncol(fixture$counts)))
  expect_message(
    result <- run_deseq2(
      counts, fixture$metadata, "condition", "AD", "Control",
      alpha = 0.05, lfc_shrink = FALSE
    ),
    "ALL_ZERO_FEATURES_REMOVED: 1"
  )
  expect_equal(result$summary$n_features, 200L)
  expect_equal(nrow(result$table), 200L)
  expect_equal(nrow(result$normalized_counts), 200L)
  expect_false("ALL_ZERO" %in% result$table$feature_id)
  expect_setequal(result$table$feature_id, rownames(fixture$counts))
  reference <- suppressMessages(run_deseq2(
    fixture$counts, fixture$metadata, "condition", "AD", "Control",
    alpha = 0.05, lfc_shrink = FALSE
  ))
  columns <- c("log2FoldChange", "pvalue", "padj")
  expect_equal(result$table[, columns], reference$table[, columns], tolerance = 1e-10)
})
