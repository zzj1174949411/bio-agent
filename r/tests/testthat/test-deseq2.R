test_that("DESeq2 comparison direction is numerator over denominator", {
  fixture <- make_bulk_fixture(seed = 42L)

  result <- run_deseq2(
    counts = fixture$counts,
    metadata = fixture$metadata,
    factor = "condition",
    numerator = "AD",
    denominator = "Control",
    alpha = 0.05,
    lfc_shrink = FALSE
  )

  expect_true(all(c("feature_id", "log2FoldChange", "pvalue", "padj") %in% names(result$table)))
  expect_gt(result$table["GENE_001", "log2FoldChange"], 0)
})

test_that("DESeq2 reverse comparison changes the log2 fold-change sign", {
  fixture <- make_bulk_fixture(seed = 42L)

  result <- run_deseq2(
    counts = fixture$counts,
    metadata = fixture$metadata,
    factor = "condition",
    numerator = "Control",
    denominator = "AD",
    alpha = 0.05,
    lfc_shrink = FALSE
  )

  expect_lt(result$table["GENE_001", "log2FoldChange"], 0)
})

test_that("DESeq2 reorders shuffled metadata and returns a fixed result contract", {
  fixture <- make_bulk_fixture(seed = 42L)
  shuffled <- fixture$metadata[c(4, 1, 6, 2, 5, 3), , drop = FALSE]

  result <- run_deseq2(
    counts = fixture$counts,
    metadata = shuffled,
    factor = "condition",
    numerator = "AD",
    denominator = "Control",
    alpha = 0.05,
    lfc_shrink = TRUE
  )

  expect_named(
    result,
    c("dds", "table", "normalized_counts", "pca", "size_factors", "summary"),
    ignore.order = FALSE
  )
  expect_equal(colnames(result$normalized_counts), colnames(fixture$counts))
  expect_true(is.data.frame(result$pca))
  expect_true(is.data.frame(result$size_factors))
  expect_identical(result$summary$status, "success")
  expect_identical(
    names(result$table),
    c("feature_id", "baseMean", "log2FoldChange", "lfcSE", "stat", "pvalue", "padj")
  )
  raw <- DESeq2::results(
    result$dds,
    contrast = c("bioagent_condition", "AD", "Control"),
    alpha = 0.05
  )
  raw <- raw[match(result$table$feature_id, rownames(raw)), ]
  expect_equal(result$table$stat, raw$stat)
  expect_equal(result$table$pvalue, raw$pvalue)
  expect_equal(result$table$padj, raw$padj)
  expect_true(any(abs(result$table$log2FoldChange - raw$log2FoldChange) > 1e-4))
  expect_gt(result$table["GENE_001", "log2FoldChange"], 0)
})

test_that("factor names are treated as data rather than formula code", {
  fixture <- make_bulk_fixture(seed = 42L)
  hostile_factor <- "condition + I(1)"
  fixture$metadata[[hostile_factor]] <- fixture$metadata$condition

  result <- run_deseq2(
    counts = fixture$counts,
    metadata = fixture$metadata,
    factor = hostile_factor,
    numerator = "AD",
    denominator = "Control",
    alpha = 0.05,
    lfc_shrink = FALSE
  )

  expect_identical(result$summary$factor, hostile_factor)
})

test_that("DESeq2 inputs reject a missing factor with a stable code", {
  fixture <- make_bulk_fixture(seed = 42L)

  expect_error(
    validate_deseq2_inputs(fixture$counts, fixture$metadata, "missing_factor", "AD", "Control"),
    regexp = "MISSING_FACTOR",
    fixed = TRUE
  )
})

test_that("DESeq2 inputs reject mismatched samples with a stable code", {
  fixture <- make_bulk_fixture(seed = 42L)
  incomplete_metadata <- fixture$metadata[-1, , drop = FALSE]

  expect_error(
    validate_deseq2_inputs(fixture$counts, incomplete_metadata, "condition", "AD", "Control"),
    regexp = "SAMPLE_SET_MISMATCH",
    fixed = TRUE
  )
})

test_that("DESeq2 inputs reject a missing contrast level with a stable code", {
  fixture <- make_bulk_fixture(seed = 42L)

  expect_error(
    validate_deseq2_inputs(fixture$counts, fixture$metadata, "condition", "Disease", "Control"),
    regexp = "INVALID_COMPARISON_LEVEL",
    fixed = TRUE
  )
})

test_that("DESeq2 inputs reject duplicated metadata samples with a stable code", {
  fixture <- make_bulk_fixture(seed = 42L)
  duplicated_metadata <- rbind(fixture$metadata, fixture$metadata[1, , drop = FALSE])

  expect_error(
    validate_deseq2_inputs(fixture$counts, duplicated_metadata, "condition", "AD", "Control"),
    regexp = "DUPLICATE_SAMPLE_ID",
    fixed = TRUE
  )
})

test_that("DESeq2 inputs reject identical comparison levels", {
  fixture <- make_bulk_fixture(seed = 42L)

  expect_error(
    validate_deseq2_inputs(fixture$counts, fixture$metadata, "condition", "AD", "AD"),
    regexp = "INVALID_COMPARISON_LEVEL",
    fixed = TRUE
  )
})

test_that("DESeq2 inputs reject factors with more than two levels", {
  fixture <- make_bulk_fixture(seed = 42L)
  fixture$metadata$condition[1] <- "Other"

  expect_error(
    validate_deseq2_inputs(fixture$counts, fixture$metadata, "condition", "AD", "Control"),
    regexp = "INVALID_FACTOR_LEVEL_COUNT",
    fixed = TRUE
  )
})

test_that("DESeq2 inputs reject missing factor values", {
  fixture <- make_bulk_fixture(seed = 42L)
  fixture$metadata$condition[1] <- NA_character_

  expect_error(
    validate_deseq2_inputs(fixture$counts, fixture$metadata, "condition", "AD", "Control"),
    regexp = "MISSING_FACTOR_VALUE",
    fixed = TRUE
  )
})

test_that("DESeq2 inputs reject non-integer counts", {
  fixture <- make_bulk_fixture(seed = 42L)
  fixture$counts[1, 1] <- 1.5

  expect_error(
    validate_deseq2_inputs(fixture$counts, fixture$metadata, "condition", "AD", "Control"),
    regexp = "NON_INTEGER_COUNT",
    fixed = TRUE
  )
})

test_that("DESeq2 inputs reject negative counts", {
  fixture <- make_bulk_fixture(seed = 42L)
  fixture$counts[1, 1] <- -1

  expect_error(
    validate_deseq2_inputs(fixture$counts, fixture$metadata, "condition", "AD", "Control"),
    regexp = "NEGATIVE_COUNT",
    fixed = TRUE
  )
})

test_that("DESeq2 inputs reject non-finite counts", {
  fixture <- make_bulk_fixture(seed = 42L)
  fixture$counts[1, 1] <- Inf

  expect_error(
    validate_deseq2_inputs(fixture$counts, fixture$metadata, "condition", "AD", "Control"),
    regexp = "NON_FINITE_COUNT",
    fixed = TRUE
  )
})

test_that("DESeq2 inputs reject duplicate feature IDs", {
  fixture <- make_bulk_fixture(seed = 42L)
  rownames(fixture$counts)[2] <- rownames(fixture$counts)[1]

  expect_error(
    validate_deseq2_inputs(fixture$counts, fixture$metadata, "condition", "AD", "Control"),
    regexp = "DUPLICATE_FEATURE_ID",
    fixed = TRUE
  )
})

test_that("DESeq2 inputs reject duplicate sample IDs", {
  fixture <- make_bulk_fixture(seed = 42L)
  colnames(fixture$counts)[2] <- colnames(fixture$counts)[1]

  expect_error(
    validate_deseq2_inputs(fixture$counts, fixture$metadata, "condition", "AD", "Control"),
    regexp = "DUPLICATE_SAMPLE_ID",
    fixed = TRUE
  )
})

test_that("DESeq2 output writer creates the complete artifact contract", {
  fixture <- make_bulk_fixture(seed = 42L)
  result <- run_deseq2(
    counts = fixture$counts,
    metadata = fixture$metadata,
    factor = "condition",
    numerator = "AD",
    denominator = "Control",
    alpha = 0.05,
    lfc_shrink = FALSE
  )
  output_dir <- file.path(tempdir(), "deseq2-output-contract")

  paths <- write_deseq2_outputs(result, output_dir)

  expect_length(paths, 15L)
  expect_true(all(file.exists(file.path(output_dir, paths))))
  expect_true(file.exists(file.path(output_dir, "results", "execution_summary.json")))
  expect_true(file.exists(file.path(output_dir, "figures", "volcano_plot.pdf")))
})

test_that("DESeq2 inputs reject zero-size libraries", {
  fixture <- make_bulk_fixture(seed = 42L)
  fixture$counts[, 1] <- 0L

  expect_error(
    validate_deseq2_inputs(fixture$counts, fixture$metadata, "condition", "AD", "Control"),
    regexp = "ZERO_LIBRARY_SIZE",
    fixed = TRUE
  )
})

test_that("DESeq2 writer creates the declared artifacts", {
  fixture <- make_bulk_fixture(seed = 42L)
  result <- run_deseq2(
    fixture$counts,
    fixture$metadata,
    "condition",
    "AD",
    "Control",
    alpha = 0.05,
    lfc_shrink = FALSE
  )
  output_dir <- file.path(tempdir(), "bio-agent-deseq2-output")
  unlink(output_dir, recursive = TRUE, force = TRUE)

  paths <- write_deseq2_outputs(result, output_dir)

  expect_true(length(paths) >= 15L)
  expect_true(all(file.exists(file.path(output_dir, paths))))
  expect_true(file.exists(file.path(output_dir, "results", "execution_summary.json")))
})

test_that("DESeq2 PCA columns remain stable when factor names collide", {
  fixture <- make_bulk_fixture(seed = 42L)
  fixture$metadata$PC1 <- fixture$metadata$condition

  result <- run_deseq2(
    fixture$counts,
    fixture$metadata,
    "PC1",
    "AD",
    "Control",
    alpha = 0.05,
    lfc_shrink = FALSE
  )

  expect_true(all(c("PC1", "PC2", "sample_id", "factor_level") %in% names(result$pca)))
  expect_true(all(result$pca$factor_level %in% c("AD", "Control")))
})
