export type OpenApiValidator = ((data: unknown) => boolean) & {
  errors: ReadonlyArray<{
    instancePath?: string;
    message?: string;
  }> | null;
};

export const validateState: OpenApiValidator;
export const validateActionResponse: OpenApiValidator;
export const validateProblem: OpenApiValidator;
export const validateEvent: OpenApiValidator;
export const validateSnapshot: OpenApiValidator;
